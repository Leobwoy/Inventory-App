"""Choosing a theme — Phase B2 of the redesign.

The plumbing only. After this commit a person can store a preference and the
attributes appear on `<html>`, but nothing changes colour: the light palette
lands in Phase C. That split is deliberate — if the dark theme breaks, it broke
in the palette or in the tokenising, never in the wiring.

The one genuinely subtle thing here is why the attribute must always be present
and concrete. Bootstrap 5.3 scopes its variables as `:root,[data-bs-theme=light]`
and ships no `prefers-color-scheme` support, so a *missing* attribute is not
neutral — it is Bootstrap's light theme. Leaving it off is the state the app has
been in all along.
"""
import pytest

from auth.models import AuditLog, User
from extensions import db


@pytest.fixture
def owner(register):
    client, business_id = register()
    return client, business_id


def html_tag(body):
    return body[body.index('<html'):body.index('>', body.index('<html')) + 1]


# --- what lands on <html> ----------------------------------------------------

def test_a_new_user_follows_their_device(owner):
    """`system` is the default, and it has to survive to the browser as itself —
    the server never sees prefers-color-scheme, so it cannot resolve it."""
    client, _business_id = owner

    tag = html_tag(client.get('/').get_data(as_text=True))

    assert 'data-theme-pref="system"' in tag


def test_the_server_still_renders_a_concrete_theme(owner):
    """With JavaScript off you get the app exactly as it was, rather than a page
    with no theme at all."""
    client, _business_id = owner

    tag = html_tag(client.get('/').get_data(as_text=True))

    assert 'data-theme="dark"' in tag
    assert 'data-bs-theme="dark"' in tag


def test_bootstrap_is_told_the_theme_too(owner):
    """Bootstrap scopes its variables as `:root,[data-bs-theme=light]`, so a
    missing attribute means every modal, dropdown and toast quietly renders on
    Bootstrap's *light* defaults inside a dark app."""
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)

    assert 'data-bs-theme=' in html_tag(body)


def test_an_explicit_choice_is_rendered_by_the_server(owner):
    client, _business_id = owner
    client.post('/auth/theme', data={'theme': 'light'})

    tag = html_tag(client.get('/').get_data(as_text=True))

    assert 'data-theme-pref="light"' in tag
    assert 'data-theme="light"' in tag
    assert 'data-bs-theme="light"' in tag


def test_the_signed_out_pages_still_have_a_theme(client):
    """Login and register render through the same base, and a page with no
    attribute would fall through to Bootstrap's light defaults."""
    tag = html_tag(client.get('/auth/login').get_data(as_text=True))

    assert 'data-theme="dark"' in tag
    assert 'data-bs-theme="dark"' in tag


# --- the resolver that runs before paint -------------------------------------

def test_system_is_resolved_before_anything_paints(owner):
    """A deferred or bottom-of-body script would let the server's dark render
    paint first, so every system-light user gets a flash of dark on every single
    page load."""
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)

    head = body[body.index('<head>'):body.index('</head>')]
    script = head[head.index('<script>'):head.index('</script>')]

    assert 'prefers-color-scheme: light' in script
    assert 'data-bs-theme' in script
    # Blocking: no defer, no async, and ahead of the stylesheets it affects.
    assert head.index('<script>') < head.index('css/style.css')


def test_the_resolver_leaves_an_explicit_choice_alone(owner):
    """Someone who picked dark on a light phone must keep dark."""
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)
    script = body[body.index('<script>'):body.index('</script>')]

    assert "themePref !== 'system'" in script


def test_a_broken_resolver_cannot_break_the_page(owner):
    """matchMedia is missing in some embedded webviews. Losing the preference is
    survivable; losing the page is not."""
    client, _business_id = owner
    script = client.get('/').get_data(as_text=True)
    script = script[script.index('<script>'):script.index('</script>')]

    assert 'try' in script and 'catch' in script


# --- storing it ---------------------------------------------------------------

def test_a_choice_is_remembered(owner):
    client, _business_id = owner

    response = client.post('/auth/theme', data={'theme': 'dark'})

    assert response.status_code == 204
    assert User.query.filter_by(email='owner@ab.example.com').one().theme_pref == 'dark'


def test_going_back_to_following_the_device_is_possible(owner):
    """'system' has to be storable, not just an initial state. Otherwise the
    first choice is permanent."""
    client, _business_id = owner
    client.post('/auth/theme', data={'theme': 'light'})
    client.post('/auth/theme', data={'theme': 'system'})

    assert User.query.filter_by(email='owner@ab.example.com').one().theme_pref == 'system'


def test_an_unknown_theme_is_refused(owner):
    client, _business_id = owner
    client.post('/auth/theme', data={'theme': 'light'})

    response = client.post('/auth/theme', data={'theme': 'neon'})

    assert response.status_code == 400
    assert User.query.filter_by(email='owner@ab.example.com').one().theme_pref == 'light'


def test_choosing_the_same_theme_twice_records_one_change(owner):
    """The control is a toggle on a page that may be tapped twice. Two audit
    entries for one decision is noise in the record someone may later have to
    read."""
    client, _business_id = owner
    client.post('/auth/theme', data={'theme': 'light'})
    client.post('/auth/theme', data={'theme': 'light'})

    assert AuditLog.query.filter_by(action='user.theme_changed').count() == 1


def test_a_stale_read_does_not_record_a_change_nobody_made(owner):
    """The sequential case is caught by the in-memory value; this is the one it
    cannot see. `current_user` is loaded per request, so a second device — or a
    double tap whose first request has not committed — arrives holding an old
    value, decides a change is needed, and writes an audit entry for an UPDATE
    that touched nothing. The entry has to follow the rowcount, not the guess.
    """
    from sqlalchemy.orm import Session

    client, _business_id = owner
    user = User.query.filter_by(email='owner@ab.example.com').one()

    other = Session(bind=db.engine)
    try:
        other.execute(db.text('UPDATE "user" SET theme_pref = :t WHERE id = :i'),
                      {'t': 'light', 'i': user.id})
        other.commit()
    finally:
        other.close()

    response = client.post('/auth/theme', data={'theme': 'light'})

    assert response.status_code == 204
    db.session.expire_all()
    assert User.query.get(user.id).theme_pref == 'light'
    assert AuditLog.query.filter_by(action='user.theme_changed').count() == 0


def test_it_is_on_the_record(owner):
    client, business_id = owner
    owner_user = User.query.filter_by(email='owner@ab.example.com').one()

    client.post('/auth/theme', data={'theme': 'light'})

    entry = AuditLog.query.filter_by(action='user.theme_changed').one()
    assert entry.user_id == owner_user.id
    assert entry.business_id == business_id


def test_a_signed_out_visitor_cannot_set_a_theme(client):
    assert client.post('/auth/theme', data={'theme': 'light'}).status_code in (302, 401)


def test_any_staff_member_can_change_their_own(owner, make_staff):
    """Not gated on settings.manage. Settings is business-wide and Owner-only,
    so a control living only there would be unreachable for the clerk standing
    in the doorway — who is precisely who needs light."""
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['sales.view'])

    assert clerk.post('/auth/theme', data={'theme': 'light'}).status_code == 204
    assert User.query.filter_by(email='clerk@ab.example.com').one().theme_pref == 'light'


def test_one_persons_choice_is_not_everyone_elses(owner, make_staff):
    """Per user, not per business. The owner at a desk and the clerk in the sun
    want opposite things."""
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['sales.view'])
    clerk.post('/auth/theme', data={'theme': 'light'})

    assert User.query.filter_by(email='owner@ab.example.com').one().theme_pref == 'system'
    assert User.query.filter_by(email='clerk@ab.example.com').one().theme_pref == 'light'


# --- nothing looks different yet ---------------------------------------------

def test_the_light_theme_actually_repaints(owner):
    """Replaces an earlier test that asserted the opposite.

    Through Phase B2 this file pinned "wiring only, no colour change", which was
    the whole point of splitting the plumbing from the palette — a dark-theme
    regression could only have come from one commit. C1a is where that stops
    being true, so the assertion inverts rather than being deleted: the boundary
    still needs a guard, it just moved.
    """
    client, _business_id = owner
    css = client.get('/static/css/style.css').get_data(as_text=True)

    assert '[data-theme="light"]' in css

    def token(block, name):
        section = css[css.index(block):]
        section = section[:section.index('}')]
        line = [l for l in section.splitlines() if l.strip().startswith(name + ':')]
        return line[0].split(':', 1)[1].split(';')[0].strip() if line else None

    for name in ('--bg-page', '--text-primary', '--accent-primary', '--table-head-bg'):
        dark = token(':root {', name)
        light = token('[data-theme="light"] {', name)
        assert dark and light, f'{name} missing from one of the themes'
        assert dark != light, f'{name} is identical in both themes'


def test_every_dark_token_has_a_light_counterpart(owner):
    """A token defined only in :root silently keeps its dark value under light —
    which is how a white-on-white or black-on-black surface appears, with
    nothing failing anywhere."""
    import re

    client, _business_id = owner
    css = client.get('/static/css/style.css').get_data(as_text=True)

    def names(block):
        section = css[css.index(block):]
        section = section[:section.index('}')]
        return set(re.findall(r'^\s*(--[\w-]+):', section, re.M))

    dark = names(':root {')
    light = names('[data-theme="light"] {')
    # --glass-backdrop is deliberately shared: the blur is the identity in both.
    missing = dark - light - {'--glass-backdrop'}
    assert not missing, f'no light value for: {sorted(missing)}'


def test_the_accent_carries_its_own_text_colour(owner):
    """A filled button puts text *on* the accent, so the accent and the ink on
    it are two decisions. Lightening the dark accent for legible links left
    white text on pale blue at 2.54:1 until this existed."""
    client, _business_id = owner
    css = client.get('/static/css/style.css').get_data(as_text=True)

    assert css.count('--on-accent:') == 2, 'both themes must define it'
    rule = css[css.index('.btn-primary {'):]
    rule = rule[:rule.index('}')]
    assert 'var(--on-accent)' in rule
