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


def media_block(css, opener, which=0):
    """One @media block, ended at its matching brace.

    Slicing to the end of the stylesheet meant a rule several blocks later could
    satisfy an assertion about this one. `which` picks among repeats of the same
    selector; -1 takes the last.
    """
    starts = [m.start() for m in re.finditer(re.escape(opener), css)]
    assert starts, f'no {opener} block in the stylesheet'
    i = starts[which]
    depth, j = 0, css.index('{', i)
    for k in range(j, len(css)):
        if css[k] == '{':
            depth += 1
        elif css[k] == '}':
            depth -= 1
            if depth == 0:
                return css[i:k + 1]
    raise AssertionError(f'{opener} is never closed')


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


# --- two ways the sidebar could fail quietly ---------------------------------

def test_a_credit_only_user_can_reach_money_owed(register, make_staff):
    """The Credit link renders on credit.view + credit_ledger, but the group
    around it rendered only on sales.view or customers.view. Someone holding
    just credit.view therefore had the link built into a group that never
    appeared - present in the template, unreachable on the page."""
    _owner, business_id = register()
    clerk = make_staff(business_id, 'Sales Staff', 'credit@ab.example.com',
                       permissions=['credit.view'])

    body = clerk.get('/').get_data(as_text=True)

    assert 'id="nav-group-sales"' in body
    assert 'id="nav-credit"' in body


def test_a_stored_null_cannot_take_the_sidebar_down(register):
    """`JSON.parse('null')` does not throw, it returns null - so the try/catch
    around it never fires, and reading a key off null throws a TypeError inside
    DOMContentLoaded. Everything registered after that never binds, including
    the mobile drawer toggle, so the menu button stops working on phones."""
    client, _business_id = register()
    body = client.get('/').get_data(as_text=True)

    assert "typeof parsed === 'object'" in body
    assert 'Array.isArray(parsed)' in body


# --- the rail ----------------------------------------------------------------

def test_every_nav_item_still_carries_its_words(register):
    """The sidebar narrowed from 260px to 140px, icon above label rather than
    beside it. Icons alone would have saved another 50px and cost every new
    staff member their first morning guessing what a picture means, and hover,
    the usual answer, does not exist on a phone.

    Asserted against the sidebar alone. The first version of this ended in
    `or word in body`, which every one of these words satisfies from the page
    content by itself - it would have stayed green with the labels stripped
    out entirely.
    """
    client, _business_id = register()
    nav = sidebar(client.get('/').get_data(as_text=True))

    for word in ('Dashboard', 'Needs attention', 'Products', 'Catalogue',
                 'Sales', 'Purchasing', 'Reports', 'Administration'):
        assert word in nav, f'{word} lost its label'


def test_the_rail_is_desktop_only(register):
    """Below 992px the sidebar is a slide-out drawer with room to spare, so it
    keeps full-width rows. Narrowing it there would shrink a menu that already
    had the whole screen."""
    client, _business_id = register()
    css = client.get('/static/css/style.css').get_data(as_text=True)

    mobile = media_block(css, '@media (max-width: 991.98px)', which=-1)
    # Anchored: a bare `'width: 260px' in mobile` is also satisfied by the
    # `min-width` on the next line, so the width itself could go and this would
    # not notice.
    assert re.search(r'(?<!-)width:\s*260px', mobile), 'the drawer must stay wide'
    assert 'flex-direction: row' in mobile, 'rows go back to icon-beside-word'


def test_the_tour_can_still_find_every_anchor(register, make_product):
    """The tour points at seven ids that live in this sidebar, and a step whose
    anchor is missing is dropped **silently** — by design, so permissions work.
    Restructuring the nav could therefore shorten the tour with nothing
    reporting it."""
    import re

    client, business_id = register()
    make_product(business_id, sku='BA-750')
    body = client.get('/').get_data(as_text=True)

    steps = re.search(r'var steps = \[(.*?)\];', body, re.S)
    assert steps, 'the tour step list is gone'
    anchors = re.findall(r"anchor:\s*'#([^']+)'", steps.group(1))
    assert len(anchors) >= 6, f'only {len(anchors)} steps survived'

    for anchor in anchors:
        assert f'id="{anchor}"' in body, f'the tour points at #{anchor}, which is gone'


# --- the phone tab bar --------------------------------------------------------

def test_the_phone_bar_offers_the_four_things_people_open_the_app_to_do(register):
    """The drawer needs a stretch to the top-left corner — the hardest place to
    reach one-handed, and this app is used one-handed, standing up."""
    client, _business_id = register()
    body = client.get('/').get_data(as_text=True)

    for tab in ('tab-today', 'tab-sell', 'tab-stock', 'tab-owed', 'tab-more'):
        assert f'id="{tab}"' in body, f'{tab} is missing from the phone bar'


def test_the_bar_respects_permissions_like_every_other_link(register, make_staff):
    """A clerk who cannot record a sale must not be given a Sell button that
    403s. The bar flexes to whatever survives, so three tabs share the width
    evenly rather than leaving a hole."""
    _client, business_id = register()
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['products.view'])

    body = clerk.get('/').get_data(as_text=True)

    assert 'id="tab-stock"' in body
    assert 'id="tab-sell"' not in body
    assert 'id="tab-owed"' not in body
    assert 'id="tab-more"' in body          # always, it is the way to everything


def test_more_opens_the_same_drawer_as_the_hamburger(register):
    """One menu, not two lists that can disagree about what exists."""
    client, _business_id = register()
    body = client.get('/').get_data(as_text=True)

    script = body[body.index("const moreTab"):body.index('</script>', body.index("const moreTab"))]
    assert "sidebar.classList.add('show')" in script


def test_the_bar_is_phone_only(register):
    """Above 768px the rail already answers the question, and a second
    navigation would be two answers to it."""
    client, _business_id = register()
    css = client.get('/static/css/style.css').get_data(as_text=True)

    default = css[css.index('.phone-tabs {'):]
    default = default[:default.index('}')]
    assert 'display: none' in default

    phone = css[css.index('@media (max-width: 767.98px)'):]
    assert 'display: flex' in phone[:phone.index('.phone-tab {')]


def test_the_page_does_not_end_underneath_the_bar(register):
    """It is fixed, so without room reserved the last thing on every page sits
    behind it — including the Record Sale button at the foot of the form."""
    client, _business_id = register()
    css = client.get('/static/css/style.css').get_data(as_text=True)

    phone = css[css.index('@media (max-width: 767.98px)'):]
    assert 'padding-bottom: calc(70px' in phone
    # And clear of the iOS home indicator, which sits on top of everything.
    assert 'safe-area-inset-bottom' in phone
