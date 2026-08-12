"""The sidebar: collapsible groups, and nothing lost in the folding.

Fifteen links is past the point where anyone reads a list, so the four labelled
sections became collapsible groups. The risk in that change is not the animation
— it is quietly dropping a link, or worse, showing a heading to someone who is
allowed none of what is inside it.

Visibility here is cosmetic: every route below carries its own
`@permission_required`, and `tests/test_permissions.py` is what proves that. What
these tests protect is that the menu tells the truth about what is reachable.
"""
import re

import pytest

#: Every link an Owner should be able to reach from the sidebar. Written out
#: rather than derived, so that losing one during a restructure fails here
#: instead of being noticed months later by a customer who cannot find Brands.
OWNER_LINKS = {
    'nav-dashboard', 'nav-alerts', 'nav-products',
    'nav-categories', 'nav-item-groups', 'nav-brands',
    'nav-sales', 'nav-customers', 'nav-credit',
    'nav-purchases', 'nav-suppliers', 'nav-compare',
    'nav-reports',
    'nav-settings', 'nav-billing', 'nav-users', 'nav-audit', 'nav-backup',
}

GROUPS = ['nav-group-catalogue', 'nav-group-sales',
          'nav-group-purchasing', 'nav-group-admin']


def sidebar(body):
    """Just the sidebar, so a match in the page body cannot be mistaken for nav."""
    start = body.find('<aside class="sidebar"')
    end = body.find('</aside>', start)
    assert start != -1 and end != -1, 'the sidebar did not render at all'
    return body[start:end]


@pytest.fixture
def owner(register):
    client, business_id = register()
    return client, business_id


# --- nothing lost -------------------------------------------------------------

def test_an_owner_still_reaches_every_link(owner):
    """The regression that matters. Folding a menu is exactly the change that
    loses an item without anyone noticing."""
    client, _business_id = owner
    nav = sidebar(client.get('/').get_data(as_text=True))

    missing = {link for link in OWNER_LINKS if f'id="{link}"' not in nav}
    assert not missing, f'these links vanished from the sidebar: {sorted(missing)}'


def test_every_group_renders_as_a_collapsible_panel(owner):
    client, _business_id = owner
    nav = sidebar(client.get('/').get_data(as_text=True))

    for group in GROUPS:
        assert f'id="{group}"' in nav, f'{group} is missing'
        assert f'data-bs-target="#{group}"' in nav, f'{group} has no toggle'


def test_the_toggles_say_what_they_control(owner):
    """A button that collapses a panel and never says so is unusable without a
    mouse and unreadable to a screen reader."""
    client, _business_id = owner
    nav = sidebar(client.get('/').get_data(as_text=True))

    for group in GROUPS:
        assert f'aria-controls="{group}"' in nav
    assert nav.count('aria-expanded') >= len(GROUPS)


# --- a heading is never shown over an empty group -----------------------------

def test_a_clerk_sees_no_administration_heading(owner, make_staff):
    """The trap in grouping. The old markup guarded the label with the same
    condition as its links; a group that kept the panel but dropped that guard
    would show Administration to someone allowed none of it."""
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['products.view', 'sales.view'])

    nav = sidebar(clerk.get('/').get_data(as_text=True))

    assert 'Administration' not in nav
    assert 'nav-group-admin' not in nav
    assert 'nav-settings' not in nav
    assert 'nav-users' not in nav


def test_a_clerk_sees_no_catalogue_heading(owner, make_staff):
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['products.view', 'sales.view'])

    nav = sidebar(clerk.get('/').get_data(as_text=True))

    assert 'nav-group-catalogue' not in nav
    assert 'nav-brands' not in nav


def test_a_group_still_shows_when_only_one_child_is_permitted(owner, make_staff):
    """The other half of the same rule: partial permission must not hide the
    group, or the one page they can open becomes unreachable."""
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['products.view', 'sales.view'])

    nav = sidebar(clerk.get('/').get_data(as_text=True))

    assert 'nav-group-sales' in nav
    assert 'nav-sales' in nav
    assert 'nav-customers' not in nav       # not granted
    assert 'nav-credit' not in nav          # not granted


def test_the_group_count_matches_what_the_person_may_use(owner, make_staff):
    """Counted, not spot-checked: an extra heading rendering for a clerk is the
    failure this whole section exists to prevent."""
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['products.view', 'sales.view'])

    nav = sidebar(clerk.get('/').get_data(as_text=True))

    assert len(re.findall(r'class="nav-group"', nav)) == 1


# --- where you are ------------------------------------------------------------

def test_the_page_you_are_on_is_inside_a_group_that_can_open(owner):
    """Landing on Settings with the sidebar showing no sign of where you are is
    the thing that makes a folded menu feel broken. The group holding the active
    link is opened on load, which needs the link and the panel both present."""
    client, _business_id = owner
    nav = sidebar(client.get('/auth/settings').get_data(as_text=True))

    admin = nav[nav.index('id="nav-group-admin"'):]
    assert 'nav-settings' in admin


def test_the_sidebar_opens_the_group_holding_the_current_page(owner):
    client, _business_id = owner
    body = client.get('/auth/settings').get_data(as_text=True)

    # The script that does it must actually be on the page; the markup alone
    # renders every group shut.
    assert 'nav-link.active' in body
    assert "classList.toggle('show', open)" in body


def test_a_corrupt_remembered_state_cannot_break_the_sidebar(owner):
    """localStorage is writable by anything that has run on this origin, and a
    JSON parse failure in a DOMContentLoaded handler stops every listener
    registered after it - including the mobile drawer toggle."""
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)

    assert 'catch' in body
    assert re.search(r"JSON\.parse\(localStorage\.getItem\('navGroups'\)[^)]*\)", body)
