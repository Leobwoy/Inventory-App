"""The gate a new staff member meets on their first sign-in.

A staff password is typed by whoever created the account, so until it is changed
that person can sign in as them. The gate holds them on one page until they set
their own.

None of this had a test, which is exactly how it shipped broken: every fixture in
conftest sets must_change_password=False, so no test ever walked through the
door. The form rendered into a block base.html only emits for signed-out users,
so a signed-in staff member got a sidebar, a banner, and no form - no way
forward and no way to work.
"""
import pytest

from auth.models import User
from extensions import db

TEMPORARY = 'temp-pass-123'
CHOSEN = 'my-own-password-9'


@pytest.fixture
def new_staff(app, register, make_staff):
    """A staff account still on the password its owner typed for them."""
    _owner, business_id = register()
    client = make_staff(business_id, 'Sales Staff', 'kwame@ab.example.com')
    user = User.query.filter_by(email='kwame@ab.example.com').one()
    user.must_change_password = True
    db.session.commit()
    return client, user


# --- the page has to actually be usable --------------------------------------

def test_the_change_password_page_has_a_form_on_it(new_staff):
    """The bug as reported: the banner said change your password, and the page
    it sent you to had nothing to change it with."""
    client, _user = new_staff

    body = client.get('/auth/change_password').get_data(as_text=True)

    assert 'name="new_password"' in body
    assert 'name="confirm_password"' in body
    assert '<form' in body


def test_the_gate_does_not_offer_a_sidebar_that_goes_nowhere(new_staff):
    """Every link in it bounces straight back here, so showing it is an
    invitation to a locked door."""
    client, _user = new_staff

    body = client.get('/auth/change_password').get_data(as_text=True)

    assert 'class="sidebar"' not in body


def test_the_page_says_why_they_are_on_it(new_staff):
    client, _user = new_staff

    body = client.get('/auth/change_password').get_data(as_text=True)

    assert 'Your password was set for you' in body


def test_the_gate_uses_the_shell_that_clears_the_mobile_header(new_staff):
    """`.auth-shell` is what reserves the 60px the fixed header occupies.

    Without it the card centres over the whole viewport, and a card taller than
    the screen pushes its own heading up behind that bar - which is what this
    page did, because its explanation runs to two lines.
    """
    client, _user = new_staff

    body = client.get('/auth/change_password').get_data(as_text=True)

    assert 'auth-shell' in body


# --- the gate itself ---------------------------------------------------------

def test_every_other_page_sends_them_back(new_staff):
    client, _user = new_staff

    for path in ('/', '/products/', '/sales/', '/products/alerts'):
        response = client.get(path)
        assert response.status_code == 302, path
        assert '/auth/change_password' in response.headers['Location'], path


def test_they_can_still_sign_out(new_staff):
    """The one way out that must never be blocked - otherwise a mistyped
    temporary password traps someone in a page they cannot use."""
    client, _user = new_staff

    assert client.get('/auth/logout').status_code in (200, 302)
    assert client.get('/auth/login').status_code == 200


def test_the_banner_does_not_pile_up(new_staff):
    """It arrived two and three at a time. The badge counter fetches on every
    page and is blocked here too, so each background request queued another
    message into the session for the next render to show."""
    client, _user = new_staff

    client.get('/products/alerts/count')       # the background fetch, blocked
    client.get('/')                            # another, for good measure
    body = client.get('/auth/change_password').get_data(as_text=True)

    assert body.count('temporary password') == 0
    assert body.count('Your password was set for you') == 1


def test_a_background_fetch_gets_an_answer_it_can_read(new_staff):
    """Not a redirect to HTML that a fetch would try to parse as JSON."""
    client, _user = new_staff

    response = client.post('/api/v1/sales', json={'sales': []})

    assert response.status_code == 403
    assert response.get_json()['code'] == 'password_change_required'


# --- setting it ---------------------------------------------------------------

def test_setting_a_password_opens_the_app(new_staff):
    client, user = new_staff

    response = client.post('/auth/change_password',
                           data={'new_password': CHOSEN,
                                 'confirm_password': CHOSEN},
                           follow_redirects=False)

    assert response.status_code == 302
    assert db.session.get(User, user.id).must_change_password is False
    assert client.get('/').status_code == 200


def test_the_new_password_is_the_one_that_works_afterwards(app, new_staff):
    """The point of the whole exercise. Asserted by signing in again rather than
    by reading the hash, because a gate that does not change the password is the
    failure worth catching."""
    from werkzeug.security import check_password_hash

    client, user = new_staff
    client.post('/auth/change_password',
                data={'new_password': CHOSEN, 'confirm_password': CHOSEN})

    stored = db.session.get(User, user.id)
    assert check_password_hash(stored.password_hash, CHOSEN)
    assert not check_password_hash(stored.password_hash, TEMPORARY)


def test_a_mismatched_confirmation_is_refused(new_staff):
    client, user = new_staff

    body = client.post('/auth/change_password',
                       data={'new_password': CHOSEN,
                             'confirm_password': 'something-else'}
                       ).get_data(as_text=True)

    assert 'Passwords must match' in body
    assert db.session.get(User, user.id).must_change_password is True


def test_a_short_password_is_refused(new_staff):
    client, user = new_staff

    body = client.post('/auth/change_password',
                       data={'new_password': 'short', 'confirm_password': 'short'}
                       ).get_data(as_text=True)

    assert 'at least 8 characters' in body
    assert db.session.get(User, user.id).must_change_password is True


def test_an_owner_who_registered_themselves_is_never_gated(register):
    """They chose their own password on the way in; there is nothing to change."""
    client, _business_id = register()

    assert client.get('/').status_code == 200
