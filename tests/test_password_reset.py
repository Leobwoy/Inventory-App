"""Getting back into an account nobody can sign in to.

There is no self-service reset (F-43), because email needs a provider and a
domain this project has not paid for. What exists is two people who can already
be trusted: an Owner for their own staff, and the vendor for an Owner who is
locked out of everything.

Both go through `services/passwords.reset`, and both end in the same place — a
one-time password plus `must_change_password`, so the gate in
`auth.enforce_password_change` forces the holder to replace it before reaching a
single page. A reset that handed out a working password indefinitely would be
worse than the lockout it fixes.
"""
import re

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from auth.models import AuditLog, User
from extensions import db
from services import passwords

STAFF_EMAIL = 'kwame@ab.example.com'
KNOWN = 'the-old-password-1'


def temp_from(body):
    """Pull the one-time password out of whatever page just showed it."""
    match = re.search(r'[ACDEFGHJKMNPQRTUVWXY34679]{4}-'
                      r'[ACDEFGHJKMNPQRTUVWXY34679]{4}-'
                      r'[ACDEFGHJKMNPQRTUVWXY34679]{4}', body)
    return match.group(0) if match else None


@pytest.fixture
def shop(register, make_staff):
    owner_client, business_id = register()
    make_staff(business_id, 'Sales Staff', STAFF_EMAIL)
    staff = User.query.filter_by(email=STAFF_EMAIL).one()
    # A known starting password, so "the old one stops working" can be asserted
    # rather than assumed.
    staff.password_hash = generate_password_hash(KNOWN)
    staff.must_change_password = False
    db.session.commit()
    return owner_client, business_id, staff


# --- the generated password --------------------------------------------------

def test_a_temporary_password_avoids_characters_people_misread():
    """It gets read down a phone line or typed off a WhatsApp message. O and 0,
    I and l and 1, S and 5 are how a correct password gets typed wrong twice and
    the person gives up."""
    for _ in range(50):
        generated = passwords.temporary_password()
        assert not set(generated) & set('OoIl01S5B8Z2')


def test_two_temporary_passwords_are_never_the_same():
    assert len({passwords.temporary_password() for _ in range(200)}) == 200


def test_two_resets_do_not_hand_out_the_same_password(shop, make_staff):
    """Asserted through `reset`, not the generator. A `reset` that ignored the
    generator and wrote a constant would pass every generator test above while
    giving every locked-out account in the system the same way in."""
    owner_client, business_id, staff = shop
    second = make_staff(business_id, 'Sales Staff', 'ama@ab.example.com')
    other = User.query.filter_by(email='ama@ab.example.com').one()

    first_body = owner_client.post(f'/auth/users/{staff.id}/reset_password',
                                   follow_redirects=True).get_data(as_text=True)
    second_body = owner_client.post(f'/auth/users/{other.id}/reset_password',
                                    follow_redirects=True).get_data(as_text=True)

    assert temp_from(first_body) != temp_from(second_body)


def test_a_temporary_password_satisfies_the_change_form(shop):
    """It has to be long enough for ChangePasswordForm, or the reset hands
    someone a password the very next page refuses."""
    from auth.forms import ChangePasswordForm

    generated = passwords.temporary_password()
    assert len(generated) >= 8
    minimum = next(v.min for v in ChangePasswordForm.new_password.kwargs['validators']
                   if hasattr(v, 'min'))
    assert len(generated) >= minimum


# --- an owner resetting their own staff --------------------------------------

def test_an_owner_can_reset_a_staff_password(shop):
    """The everyday case. A clerk who forgets their password on a Saturday
    should not have to reach the vendor."""
    owner_client, _business_id, staff = shop

    body = owner_client.post(f'/auth/users/{staff.id}/reset_password',
                             follow_redirects=True).get_data(as_text=True)

    temporary = temp_from(body)
    assert temporary, 'the new password was never shown to the person resetting it'
    assert check_password_hash(User.query.get(staff.id).password_hash, temporary)


def test_the_old_password_stops_working(shop, app):
    owner_client, _business_id, staff = shop
    owner_client.post(f'/auth/users/{staff.id}/reset_password')

    fresh = app.test_client()
    fresh.post('/auth/login', data={'email': STAFF_EMAIL, 'password': KNOWN},
               follow_redirects=True)

    assert fresh.get('/').status_code == 302        # never signed in


def test_the_new_password_gets_them_in_and_straight_to_the_gate(shop, app):
    """The whole point: back in, but not loose. The password is known to whoever
    performed the reset, so it must not survive the first sign-in."""
    owner_client, _business_id, staff = shop
    body = owner_client.post(f'/auth/users/{staff.id}/reset_password',
                             follow_redirects=True).get_data(as_text=True)
    temporary = temp_from(body)

    fresh = app.test_client()
    fresh.post('/auth/login', data={'email': STAFF_EMAIL, 'password': temporary},
               follow_redirects=True)

    landing = fresh.get('/')
    assert landing.status_code == 302
    assert '/auth/change_password' in landing.headers['Location']
    assert 'name="new_password"' in fresh.get('/auth/change_password').get_data(as_text=True)


def test_the_reset_is_written_to_the_business_activity_log(shop):
    """Named, not merely non-null. "Somebody reset this password" is not an
    answer anyone can act on — the Owner needs to know which of them did it."""
    owner_client, business_id, staff = shop
    owner = User.query.filter_by(email='owner@ab.example.com').one()

    owner_client.post(f'/auth/users/{staff.id}/reset_password')

    entry = AuditLog.query.filter_by(business_id=business_id,
                                     action='user.password_reset').one()
    assert entry.user_id == owner.id
    assert STAFF_EMAIL in (entry.details_json or '')


def test_the_password_itself_is_never_recorded(shop):
    """Shown once, in a flash, and nowhere else. An audit row is the last place
    a working password should be sitting."""
    owner_client, business_id, staff = shop
    body = owner_client.post(f'/auth/users/{staff.id}/reset_password',
                             follow_redirects=True).get_data(as_text=True)
    temporary = temp_from(body)

    entry = AuditLog.query.filter_by(business_id=business_id,
                                     action='user.password_reset').one()
    assert temporary not in (entry.details_json or '')
    assert temporary not in User.query.get(staff.id).password_hash


def test_resetting_your_own_password_sends_you_to_the_right_page(shop):
    owner_client, _business_id, _staff = shop
    owner = User.query.filter_by(email='owner@ab.example.com').one()

    body = owner_client.post(f'/auth/users/{owner.id}/reset_password',
                             follow_redirects=True).get_data(as_text=True)

    assert 'Change Password' in body
    assert User.query.get(owner.id).must_change_password is False


# --- the gates ---------------------------------------------------------------

def test_staff_cannot_reset_anyone(shop, make_staff):
    """`users.manage` is the gate, and only Owners hold it. Without this a clerk
    could reset the Owner's password and take the business."""
    _owner_client, business_id, staff = shop
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com')

    assert clerk.post(f'/auth/users/{staff.id}/reset_password').status_code == 403


def test_an_owner_cannot_reset_someone_in_another_business(shop, register):
    """Invariant 1. A tampered id must return 404, not another tenant's account."""
    owner_client, _business_id, _staff = shop
    _other, other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    stranger = User.query.filter_by(business_id=other_id).first()
    before = stranger.password_hash

    assert owner_client.post(
        f'/auth/users/{stranger.id}/reset_password').status_code == 404
    assert User.query.get(stranger.id).password_hash == before


def test_a_signed_out_visitor_cannot_reset_anything(shop, app):
    _owner_client, _business_id, staff = shop
    before = staff.password_hash

    response = app.test_client().post(f'/auth/users/{staff.id}/reset_password')

    assert response.status_code in (302, 401)
    assert User.query.get(staff.id).password_hash == before


# --- the vendor console: the last way back in --------------------------------

def test_the_console_can_reset_a_locked_out_owner(console, shop):
    """The case nothing else covers. The Owner holds `users.manage`, so if they
    are locked out there is nobody inside the business who can help - and the
    only other recovery would be shell access to the production database."""
    _owner_client, business_id, _staff = shop
    owner = User.query.filter_by(email='owner@ab.example.com').one()

    body = console.post(
        f'/platform/businesses/{business_id}/users/{owner.id}/reset-password',
        follow_redirects=True).get_data(as_text=True)

    temporary = temp_from(body)
    assert temporary
    assert check_password_hash(User.query.get(owner.id).password_hash, temporary)
    assert User.query.get(owner.id).must_change_password is True


def test_a_console_reset_is_visible_to_the_business_it_happened_to(console, shop):
    """Someone able to take over any account in the system leaves a mark the
    account's owner can see."""
    _owner_client, business_id, _staff = shop
    owner = User.query.filter_by(email='owner@ab.example.com').one()

    console.post(f'/platform/businesses/{business_id}/users/{owner.id}/reset-password')

    entry = AuditLog.query.filter_by(business_id=business_id,
                                     action='user.password_reset').one()
    assert 'runs@tracktrack.example.com' in (entry.details_json or '')
    assert 'platform_console' in (entry.details_json or '')


def test_a_console_reset_is_never_signed_by_a_tenant_who_happens_to_be_logged_in(
        console, shop):
    """The reason `audit.log` has an OMITTED sentinel at all.

    A platform admin uses one browser, so a tenant session from testing an
    account minutes earlier is still in the same cookie jar. Without an explicit
    `user_id=None` the entry is attributed to whoever that was — crediting a
    customer with a decision they did not make, in their own activity log, about
    their own password. Asserting `user_id is None` with no tenant session
    present proves nothing: it would be None either way.
    """
    _owner_client, business_id, staff = shop
    owner = User.query.filter_by(email='owner@ab.example.com').one()
    owner.password_hash = generate_password_hash(KNOWN)
    db.session.commit()

    signed_in = console.post('/auth/login',
                             data={'email': owner.email, 'password': KNOWN},
                             follow_redirects=True)
    assert signed_in.status_code == 200
    console.post(f'/platform/businesses/{business_id}/users/{staff.id}/reset-password')

    entry = AuditLog.query.filter_by(business_id=business_id,
                                     action='user.password_reset').one()
    assert entry.user_id is None, 'the tenant was credited with a console action'


def test_a_console_reset_does_not_record_the_password_either(console, shop):
    """The tenant path is asserted above; this is the branch that writes extra
    detail, and so the branch where a password would most easily be added."""
    _owner_client, business_id, staff = shop

    body = console.post(
        f'/platform/businesses/{business_id}/users/{staff.id}/reset-password',
        follow_redirects=True).get_data(as_text=True)
    temporary = temp_from(body)

    entry = AuditLog.query.filter_by(business_id=business_id,
                                     action='user.password_reset').one()
    assert temporary and temporary not in (entry.details_json or '')


def test_a_tenant_owner_cannot_reach_the_console_reset(shop):
    """The two worlds do not touch. An Owner holds every permission inside their
    business, so anything reachable with a tenant session is self-grantable."""
    owner_client, business_id, staff = shop
    before = staff.password_hash

    response = owner_client.post(
        f'/platform/businesses/{business_id}/users/{staff.id}/reset-password')

    assert response.status_code == 404
    assert User.query.get(staff.id).password_hash == before


def test_the_console_cannot_reset_across_businesses_by_id(console, shop, register):
    """business_id and user_id both come from the URL. Without the pairing check
    a mismatched pair would reset someone in a business the page is not showing."""
    _owner_client, business_id, _staff = shop
    _other, other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    stranger = User.query.filter_by(business_id=other_id).first()
    before = stranger.password_hash

    response = console.post(
        f'/platform/businesses/{business_id}/users/{stranger.id}/reset-password')

    assert response.status_code == 404
    assert User.query.get(stranger.id).password_hash == before


def test_the_console_lists_the_staff_it_can_reset(console, shop):
    _owner_client, business_id, _staff = shop

    body = console.get(f'/platform/businesses/{business_id}').get_data(as_text=True)

    assert STAFF_EMAIL in body
    assert 'Reset password' in body


# --- the CLI: the fallback beneath the fallback ------------------------------

def cli(app):
    return app.test_cli_runner()


def test_the_cli_resets_a_password(app, shop):
    """For when the console itself cannot be reached. Confirmed interactively,
    because this is one keystroke away from changing a customer's password."""
    from platform_console.cli import reset_user_password_command

    _owner_client, _business_id, staff = shop

    result = cli(app).invoke(reset_user_password_command,
                             [STAFF_EMAIL, '--by', 'terminal'], input='y\n')

    assert result.exit_code == 0, result.output
    temporary = temp_from(result.output)
    assert temporary
    assert check_password_hash(User.query.get(staff.id).password_hash, temporary)
    assert User.query.get(staff.id).must_change_password is True


def test_the_cli_records_who_ran_it(app, shop):
    from platform_console.cli import reset_user_password_command

    _owner_client, business_id, _staff = shop
    cli(app).invoke(reset_user_password_command,
                    [STAFF_EMAIL, '--by', 'leonard-on-call'], input='y\n')

    entry = AuditLog.query.filter_by(business_id=business_id,
                                     action='user.password_reset').one()
    assert entry.user_id is None
    assert 'leonard-on-call' in (entry.details_json or '')


def test_the_cli_refuses_an_address_it_does_not_know(app, shop):
    from platform_console.cli import reset_user_password_command

    result = cli(app).invoke(reset_user_password_command,
                             ['nobody@nowhere.example.com'], input='y\n')

    assert result.exit_code == 1
    assert 'No user' in result.output


def test_the_cli_finds_an_address_whatever_its_case(app, shop):
    """Email is stored as typed but matched case-insensitively at login, so the
    recovery path has to agree - or the address in someone's message will not
    match the address in the database."""
    from platform_console.cli import reset_user_password_command

    result = cli(app).invoke(reset_user_password_command,
                             [STAFF_EMAIL.upper()], input='y\n')

    assert result.exit_code == 0, result.output
    assert temp_from(result.output)


def test_the_cli_refuses_a_suspended_account(app, shop):
    """Login checks is_active before the password, so a reset here would hand
    over something that cannot work and say it succeeded."""
    from platform_console.cli import reset_user_password_command

    _owner_client, _business_id, staff = shop
    before = staff.password_hash
    staff.is_active = False
    db.session.commit()

    result = cli(app).invoke(reset_user_password_command, [STAFF_EMAIL], input='y\n')

    assert result.exit_code == 1
    assert 'suspended' in result.output.lower()
    assert User.query.get(staff.id).password_hash == before


def test_declining_the_confirmation_changes_nothing(app, shop):
    from platform_console.cli import reset_user_password_command

    _owner_client, _business_id, staff = shop
    before = staff.password_hash

    result = cli(app).invoke(reset_user_password_command, [STAFF_EMAIL], input='n\n')

    assert result.exit_code != 0
    assert User.query.get(staff.id).password_hash == before
    assert temp_from(result.output) is None


def test_a_failed_commit_prints_no_password_and_leaves_none_set(app, shop, monkeypatch):
    """The order that matters. A password echoed for a reset that did not commit
    is worse than an error - whoever ran this would read it out, and it would
    not work."""
    from platform_console.cli import reset_user_password_command

    _owner_client, _business_id, staff = shop
    before = staff.password_hash

    def refuse():
        raise RuntimeError('the database went away')

    monkeypatch.setattr(db.session, 'commit', refuse)
    result = cli(app).invoke(reset_user_password_command, [STAFF_EMAIL], input='y\n')
    monkeypatch.undo()

    assert result.exit_code == 1
    assert temp_from(result.output) is None
    assert 'Nothing was changed' in result.output
    db.session.rollback()
    assert User.query.get(staff.id).password_hash == before


# --- no user-controlled data inside a JavaScript string ----------------------

HOSTILE = "Kwame'); alert(document.cookie); //"


def onclick_attributes(body):
    """Every onclick="..." value on the page."""
    return re.findall(r'onclick="([^"]*)"', body)


def test_a_staff_name_never_reaches_a_javascript_string(shop, make_staff):
    """Autoescaping does not protect a JS string literal inside an attribute.

    It turns `'` into `&#39;`, the HTML parser turns that back into `'` before
    the JS parser ever runs, and a name like  Kwame'); alert(1); //  closes the
    literal and executes. The name now travels in a data attribute and is read
    back through `dataset`, so it is never parsed as code.
    """
    owner_client, business_id, _staff = shop
    make_staff(business_id, 'Sales Staff', 'hostile@ab.example.com')
    hostile = User.query.filter_by(email='hostile@ab.example.com').one()
    hostile.name = HOSTILE
    db.session.commit()

    body = owner_client.get('/auth/users').get_data(as_text=True)

    assert 'data-who' in body, 'the safe pattern is not being used at all'
    for handler in onclick_attributes(body):
        assert 'alert(' not in handler
        assert 'Kwame' not in handler


def test_a_tenant_address_never_reaches_a_javascript_string_in_the_console(
        console, shop):
    """The one that crosses a trust boundary. That address is written by the
    customer and rendered in the console — the single place that can reset any
    password in the system."""
    _owner_client, business_id, staff = shop
    staff.email = "victim'); alert(document.cookie); //@ab.example.com"
    db.session.commit()

    body = console.get(f'/platform/businesses/{business_id}').get_data(as_text=True)

    assert 'data-who' in body
    for handler in onclick_attributes(body):
        assert 'alert(' not in handler
        assert 'victim' not in handler


# --- a suspended account ------------------------------------------------------

def test_the_console_refuses_to_reset_a_suspended_account(console, shop):
    """Login checks is_active before it checks the password, so this would hand
    over something that cannot work and report success."""
    _owner_client, business_id, staff = shop
    staff.is_active = False
    db.session.commit()
    before = staff.password_hash

    body = console.post(
        f'/platform/businesses/{business_id}/users/{staff.id}/reset-password',
        follow_redirects=True).get_data(as_text=True)

    assert temp_from(body) is None
    assert 'suspended' in body.lower()
    assert User.query.get(staff.id).password_hash == before


def test_the_console_hides_the_reset_button_for_a_suspended_account(console, shop):
    _owner_client, business_id, staff = shop
    staff.is_active = False
    db.session.commit()

    body = console.get(f'/platform/businesses/{business_id}').get_data(as_text=True)

    assert 'Reinstate first' in body


def test_suspended_is_shown_even_mid_reset(console, shop):
    """It used to sit behind must_change_password, so an account that was both
    suspended and awaiting a password showed only the second — hiding the very
    thing stopping the new password from working."""
    _owner_client, business_id, staff = shop
    staff.is_active = False
    staff.must_change_password = True
    db.session.commit()

    body = console.get(f'/platform/businesses/{business_id}').get_data(as_text=True)

    assert 'Suspended' in body
