"""The console for whoever runs TrackTrack.

The first version of this put the vendor inside a tenant: a login belongs to a
business, so running the platform meant registering a business you do not own.
That was muddled, and the muddle is the dangerous kind - it puts the person who
decides what a business has paid for *inside* the population of businesses.

So the console has its own table, its own login and its own session key. What
these tests protect is that the two never meet: a tenant session grants nothing
here, and a console session grants nothing there.
"""
import datetime
from pathlib import Path

import pytest

from auth.models import Business, User
from billing.models import PaymentTransaction, Plan, Subscription
from extensions import db
from platform_console.models import PlatformAdmin

@pytest.fixture
def admin(platform_account):
    """The account behind the shared `console` fixture."""
    return platform_account


@pytest.fixture
def tenant(register, monkeypatch):
    monkeypatch.setenv('MOMO_NUMBER', '0244000111')
    monkeypatch.setenv('MOMO_NAME', 'Platform Owner')
    client, business_id = register()
    return client, business_id


def claim(client, plan_code='standard', reference='MP-CONSOLE-1'):
    client.post(f'/billing/upgrade/{plan_code}',
                data={'cycle': 'monthly', 'reference': reference, 'payer_note': ''},
                follow_redirects=True)
    return PaymentTransaction.query.filter_by(provider_ref=reference).one()


# --- the two worlds do not touch --------------------------------------------

def test_a_tenant_owner_cannot_reach_the_console(tenant):
    """The whole reason the console exists separately. An Owner holds every
    permission inside their business, so anything expressed as a permission
    would be self-grantable."""
    client, _business_id = tenant

    assert client.get('/platform/', follow_redirects=False).status_code == 302
    assert '/platform/login' in client.get('/platform/', follow_redirects=False).location
    assert client.post('/platform/payments/1/confirm', data={}).status_code == 404


def test_a_console_session_is_not_a_tenant_session(console):
    """And the other direction: being able to confirm payments must not grant
    access to anyone's stock or customers."""
    assert console.get('/products/', follow_redirects=False).status_code == 302
    assert '/auth/login' in console.get('/products/', follow_redirects=False).location


def test_signing_into_the_app_does_not_sign_you_into_the_console(tenant, admin):
    """Even when the same person owns both, they are separate sessions - the
    tenant login writes a Flask-Login id and nothing reads it here."""
    client, _business_id = tenant
    assert client.get('/platform/', follow_redirects=False).status_code == 302


def test_a_platform_admin_needs_no_business(admin):
    """The point of the separate table. A User must belong to a business; this
    account belongs to nothing, which is what it actually is."""
    assert not hasattr(admin, 'business_id')
    assert User.query.filter_by(email=admin.email).first() is None


# --- getting in -------------------------------------------------------------

def test_the_console_login_works(console):
    body = console.get('/platform/').get_data(as_text=True)
    assert 'Overview' in body
    assert 'CONSOLE' in body


def test_a_wrong_password_says_nothing_useful(app, admin):
    """One message for every failure. 'No such account' tells someone which
    addresses are worth guessing a password for."""
    from tests.conftest import CONSOLE_PASSWORD          # noqa: F401
    client = app.test_client()
    unknown = client.post('/platform/login',
                          data={'email': 'nobody@example.com', 'password': 'x' * 20},
                          follow_redirects=True).get_data(as_text=True)
    wrong = client.post('/platform/login',
                        data={'email': admin.email, 'password': 'wrong-password'},
                        follow_redirects=True).get_data(as_text=True)

    assert 'not recognised' in unknown
    assert 'not recognised' in wrong
    assert 'Overview' not in wrong


def test_a_deactivated_admin_loses_access_immediately(console, admin):
    """Checked every request rather than at sign-in, so removing someone takes
    effect now and not whenever their session happens to lapse."""
    assert console.get('/platform/').status_code == 200

    admin.is_active = False
    db.session.commit()

    assert console.get('/platform/', follow_redirects=False).status_code == 302


def test_signing_out_ends_the_console_session(console):
    # POST: signing out is a state change, and a GET logout can be triggered by
    # anything that renders a URL on your behalf.
    assert console.get('/platform/logout').status_code == 405
    console.post('/platform/logout')
    assert console.get('/platform/', follow_redirects=False).status_code == 302


# --- what the console does --------------------------------------------------

def test_the_dashboard_surfaces_what_needs_doing(console, tenant):
    client, _business_id = tenant
    claim(client)

    body = console.get('/platform/').get_data(as_text=True)
    assert 'payments to confirm' in body
    assert 'MP-CONSOLE-1' in body


def test_confirming_from_the_console_activates_the_plan(console, tenant):
    client, business_id = tenant
    transaction = claim(client)

    console.post(f'/platform/payments/{transaction.id}/confirm',
                 data={'note': 'seen on statement'}, follow_redirects=True)

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    assert PaymentTransaction.query.one().status == 'paid'
    assert subscription.status == 'active'
    assert subscription.plan.code == 'standard'


def test_the_confirmation_records_which_admin_did_it(console, tenant, admin):
    from auth.models import AuditLog
    client, _business_id = tenant
    transaction = claim(client)

    console.post(f'/platform/payments/{transaction.id}/confirm',
                 data={'note': ''}, follow_redirects=True)

    entry = AuditLog.query.filter_by(action='billing.payment_confirmed').one()
    assert admin.email in entry.details_json


def test_rejecting_requires_a_reason(console, tenant):
    client, _business_id = tenant
    transaction = claim(client)

    console.post(f'/platform/payments/{transaction.id}/reject',
                 data={'note': '   '}, follow_redirects=True)
    assert PaymentTransaction.query.one().status == 'pending'

    console.post(f'/platform/payments/{transaction.id}/reject',
                 data={'note': 'no such transaction'}, follow_redirects=True)
    assert PaymentTransaction.query.one().status == 'rejected'


def test_the_businesses_list_shows_the_plan_in_effect(console, tenant):
    _client, business_id = tenant
    business = db.session.get(Business, business_id)

    body = console.get('/platform/businesses').get_data(as_text=True)
    assert business.name in body
    assert 'Trial' in body


def test_a_business_can_be_put_on_a_plan_by_hand(console, tenant):
    """Comping an early customer, or fixing a payment that went astray."""
    _client, business_id = tenant

    console.post(f'/platform/businesses/{business_id}', data={
        'plan_code': 'advanced', 'status': 'active', 'days': '90',
        'reason': 'comped pilot customer',
    }, follow_redirects=True)

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    assert subscription.plan.code == 'advanced'
    assert subscription.status == 'active'
    assert subscription.paid_through > datetime.datetime.utcnow() + datetime.timedelta(days=80)


def test_a_hand_made_plan_change_needs_a_reason_and_is_audited(console, tenant):
    """A plan changed by hand with no stated reason is indistinguishable later
    from a mistake, and the business itself should be able to see it happened."""
    from auth.models import AuditLog
    _client, business_id = tenant

    console.post(f'/platform/businesses/{business_id}', data={
        'plan_code': 'advanced', 'status': 'active', 'days': '30', 'reason': '',
    }, follow_redirects=True)
    assert Subscription.query.filter_by(business_id=business_id).one().plan.code == 'trial'

    console.post(f'/platform/businesses/{business_id}', data={
        'plan_code': 'advanced', 'status': 'active', 'days': '30',
        'reason': 'launch partner',
    }, follow_redirects=True)

    entry = AuditLog.query.filter_by(action='billing.plan_changed_by_platform').one()
    assert entry.business_id == business_id      # visible to the business too
    assert 'launch partner' in entry.details_json


# --- the tenant app no longer carries any of this ---------------------------

def test_the_old_tenant_side_confirmation_screen_is_gone(tenant):
    client, _business_id = tenant
    assert client.get('/billing/admin/payments').status_code == 404


def test_the_tenant_sidebar_never_mentions_the_console(tenant):
    """Not security - the login is that - but a customer has no use for knowing
    a vendor console exists."""
    client, _business_id = tenant
    body = client.get('/').get_data(as_text=True)

    assert '/platform' not in body
    assert 'Confirm payments' not in body


def test_a_rejection_from_the_console_is_recorded_too(console, tenant, admin):
    """Same trap as the confirmation: audit.log infers the business from
    current_user, and the console has none. A refused claim that leaves no
    trace is a dispute nobody can settle later."""
    from auth.models import AuditLog
    client, business_id = tenant
    transaction = claim(client)

    console.post(f'/platform/payments/{transaction.id}/reject',
                 data={'note': 'not on the statement'}, follow_redirects=True)

    entry = AuditLog.query.filter_by(action='billing.payment_rejected').one()
    assert entry.business_id == business_id
    assert entry.user_id is None                 # nobody in that business did this
    assert admin.email in entry.details_json
    assert 'not on the statement' in entry.details_json


# --- the command-line fallback ----------------------------------------------

def test_the_cli_can_confirm_and_reject(app, tenant):
    """The console needs a browser and a working web layer. When either is
    unavailable the money still has to be settled, so the same service is
    reachable from a terminal - and both directions, not just granting."""
    from platform_console.cli import confirm_payment_command, reject_payment_command

    client, business_id = tenant
    claim(client, reference='MP-CLI-1')
    claim(client, plan_code='basic', reference='MP-CLI-2')

    runner = app.test_cli_runner()
    runner.invoke(confirm_payment_command, ['MP-CLI-1', '--by', 'terminal'], input='y\n')
    # An empty reason is refused here as it is in the console: a rejection with
    # nothing stated is a dispute nobody can settle later.
    blank = runner.invoke(reject_payment_command, ['MP-CLI-2', '--reason', '   '],
                          input='y\n')
    assert 'reason is required' in blank.output
    assert PaymentTransaction.query.filter_by(provider_ref='MP-CLI-2').one().status == 'pending'

    runner.invoke(reject_payment_command,
                  ['MP-CLI-2', '--reason', 'not on the statement'], input='y\n')

    assert PaymentTransaction.query.filter_by(provider_ref='MP-CLI-1').one().status == 'paid'
    assert PaymentTransaction.query.filter_by(provider_ref='MP-CLI-2').one().status == 'rejected'
    assert Subscription.query.filter_by(business_id=business_id).one().status == 'active'


def test_the_cli_refuses_a_malformed_console_account(app):
    """An empty prompt or a typo would otherwise create an account nobody can
    sign in to, and the failure would only show up at the login screen."""
    from platform_console.cli import create_platform_admin_command

    runner = app.test_cli_runner()
    bad_email = runner.invoke(create_platform_admin_command,
                              ['--email', 'not-an-address', '--name', 'X',
                               '--password', 'a-long-enough-password'])
    no_name = runner.invoke(create_platform_admin_command,
                            ['--email', 'ok@example.com', '--name', '   ',
                             '--password', 'a-long-enough-password'])
    short = runner.invoke(create_platform_admin_command,
                          ['--email', 'ok@example.com', '--name', 'X',
                           '--password', 'short'])

    assert 'does not look like an email' in bad_email.output
    assert 'A name is required' in no_name.output
    assert 'at least 12 characters' in short.output
    assert PlatformAdmin.query.count() == 0


def test_the_cli_will_not_settle_a_payment_twice(app, tenant):
    from platform_console.cli import confirm_payment_command

    client, _business_id = tenant
    claim(client, reference='MP-CLI-3')

    runner = app.test_cli_runner()
    runner.invoke(confirm_payment_command, ['MP-CLI-3'], input='y\n')
    again = runner.invoke(confirm_payment_command, ['MP-CLI-3'], input='y\n')

    assert 'already paid' in again.output


def test_the_cli_refuses_identity_fields_the_columns_cannot_hold(app):
    """email is 120 characters and name is 100. Letting Postgres be the one to
    complain produces a StringDataRightTruncation traceback rather than a
    sentence anyone can act on."""
    from platform_console.cli import create_platform_admin_command

    runner = app.test_cli_runner()
    long_email = runner.invoke(create_platform_admin_command,
                               ['--email', 'a' * 120 + '@example.com', '--name', 'X',
                                '--password', 'a-long-enough-password'])
    long_name = runner.invoke(create_platform_admin_command,
                              ['--email', 'ok@example.com', '--name', 'N' * 101,
                               '--password', 'a-long-enough-password'])

    assert 'too long' in long_email.output
    assert 'too long' in long_name.output
    assert PlatformAdmin.query.count() == 0


# --- the console has to be legible ------------------------------------------

def test_the_console_sets_the_table_variables_bootstrap_actually_reads():
    """Bootstrap 5.3 colours table cells from --bs-table-color, set on the cells
    themselves - so a `color` on .table never reaches them. The console rendered
    every table in Bootstrap's default near-black on a near-black panel, and the
    text was invisible until someone underlined it in a screenshot to show me."""
    import re
    source = (Path(__file__).resolve().parent.parent
              / 'templates' / 'platform' / 'base.html').read_text(encoding='utf-8')
    css = re.sub(r'\{#.*?#\}', '', source, flags=re.S)

    assert '--bs-table-color:' in css
    assert '--bs-table-bg:' in css
    # Hover swaps the colour too, so it needs the same treatment.
    assert '--bs-table-hover-color:' in css


def test_the_console_overrides_bootstraps_light_page_semantics():
    """text-success is #198754, chosen for a white page. On this one it lands at
    4.16:1 - under WCAG AA - and it is the headline figure on the dashboard."""
    import re
    source = (Path(__file__).resolve().parent.parent
              / 'templates' / 'platform' / 'base.html').read_text(encoding='utf-8')
    css = re.sub(r'\{#.*?#\}', '', source, flags=re.S)

    for name in ('text-success', 'text-danger', 'text-warning'):
        assert re.search(rf'\.{name}\s*\{{[^}}]*color:[^}}]*!important', css), (
            f'.{name} still uses the light-page default')
