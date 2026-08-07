"""Paying by mobile money, confirmed by a person.

Paystack needs a registered company and a corporate bank account, which is a
real barrier and not a technical one. So collection is manual for now: the
customer sends money to the platform's own wallet and types the transaction ID,
and someone checks it against the statement before anything is activated.

This is less of a compromise than it sounds. **Mobile money in Ghana cannot do
recurring charges** - there is no reusable authorisation the way there is for a
card - so even a fully automated integration needs the customer to actively pay
again every month. Automation only changes who presses confirm.

What these tests protect is the boundary that makes it safe: a customer can
*claim* a payment, and only the platform can *confirm* one.
"""
import datetime
from decimal import Decimal

import pytest

from billing import providers
from billing.models import PaymentTransaction, Plan, Subscription
from extensions import db
from services import billing as billing_service
from services import limits

MOMO_ENV = {'MOMO_NUMBER': '0244000111', 'MOMO_NAME': 'Leonard Mensah', 'MOMO_NETWORK': 'MTN'}


@pytest.fixture
def shop(register, monkeypatch):
    for key, value in MOMO_ENV.items():
        monkeypatch.setenv(key, value)
    client, business_id = register()
    return client, business_id


@pytest.fixture
def platform_admin(shop, monkeypatch, app):
    """The owner of the shop, also named as a platform admin."""
    client, business_id = shop
    from auth.models import User
    email = User.query.filter_by(business_id=business_id).first().email
    monkeypatch.setenv('PLATFORM_ADMIN_EMAILS', email)
    return client, business_id


def claim(client, plan_code='standard', reference='MP260805.1423.A1', cycle='monthly'):
    return client.post(f'/billing/upgrade/{plan_code}', data={
        'cycle': cycle, 'reference': reference, 'payer_note': '0244999888',
    }, follow_redirects=True)


# --- what the customer sees -------------------------------------------------

def test_the_upgrade_page_shows_where_to_send_the_money(shop):
    client, _business_id = shop
    body = client.get('/billing/upgrade/standard').get_data(as_text=True)

    assert '0244000111' in body
    assert 'Leonard Mensah' in body
    assert 'MTN' in body


def test_the_wallet_details_come_from_the_environment(monkeypatch):
    """A personal phone number in a public repository is a mistake that is hard
    to take back, and the number changes without a deploy."""
    monkeypatch.setenv('MOMO_NUMBER', '0209999999')
    monkeypatch.setenv('MOMO_NAME', 'Someone Else')
    provider = providers.ManualMomoProvider()

    assert provider.number == '0209999999'
    assert provider.account_name == 'Someone Else'
    assert provider.configured


def test_an_unconfigured_wallet_refuses_rather_than_showing_a_blank(shop, monkeypatch):
    """A page telling a customer to pay nobody is worse than no page."""
    client, _business_id = shop
    monkeypatch.delenv('MOMO_NUMBER', raising=False)

    response = client.get('/billing/upgrade/standard', follow_redirects=True)
    assert 'not available right now' in response.get_data(as_text=True)


def test_a_custom_plan_is_not_purchasable_online(shop):
    client, _business_id = shop
    response = client.get('/billing/upgrade/custom', follow_redirects=True)
    assert 'priced case by case' in response.get_data(as_text=True)


# --- claiming a payment -----------------------------------------------------

def test_a_claim_is_recorded_but_changes_nothing(shop):
    """The whole safety property. A typed reference is a claim about a payment,
    not the payment - anyone can type one."""
    client, business_id = shop
    claim(client)

    transaction = PaymentTransaction.query.one()
    assert transaction.status == 'pending'
    assert transaction.amount_ghs == Decimal('199.00')      # Depot, monthly
    assert transaction.provider == 'manual_momo'

    # Still on the trial plan it registered with. Nothing was granted.
    assert Subscription.query.filter_by(business_id=business_id).one().status == 'trialing'


def test_the_amount_comes_from_the_plan_not_the_request(shop):
    """A posted price is a request to be charged less, and this is the one place
    that could honour it."""
    client, _business_id = shop
    client.post('/billing/upgrade/standard', data={
        'cycle': 'monthly', 'reference': 'MP-CHEAP', 'payer_note': '',
        'amount_ghs': '1.00', 'amount': '1.00', 'price': '1.00',
    }, follow_redirects=True)

    assert PaymentTransaction.query.one().amount_ghs == Decimal('199.00')


def test_the_same_transaction_id_cannot_be_claimed_twice(shop, register, monkeypatch):
    """Otherwise one payment buys two subscriptions - including for two
    different businesses, which is the version that costs real money."""
    client, _business_id = shop
    claim(client, reference='MP-SHARED')

    other, _other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    response = claim(other, reference='MP-SHARED')

    assert 'already been submitted' in response.get_data(as_text=True)
    assert PaymentTransaction.query.filter_by(provider_ref='MP-SHARED').count() == 1


def test_an_annual_claim_covers_a_year(shop):
    client, _business_id = shop
    claim(client, cycle='annual')

    transaction = PaymentTransaction.query.one()
    assert transaction.amount_ghs == Decimal('1990.00')
    assert (transaction.period_end - transaction.period_start).days == billing_service.YEAR_DAYS


# --- only the platform may confirm ------------------------------------------

def test_a_tenant_cannot_reach_the_confirmation_screen(shop):
    """A tenant Owner holds every permission inside their own business, so this
    cannot be gated on a permission - they would simply grant it to themselves."""
    client, _business_id = shop
    assert client.get('/billing/admin/payments').status_code == 404


def test_a_tenant_cannot_confirm_their_own_payment(shop):
    client, business_id = shop
    claim(client)
    transaction = PaymentTransaction.query.one()

    response = client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                           data={'note': ''}, follow_redirects=True)

    assert response.status_code == 404
    assert PaymentTransaction.query.one().status == 'pending'
    assert Subscription.query.filter_by(business_id=business_id).one().status == 'trialing'


def test_the_screen_hides_rather_than_forbids(shop):
    """404, not 403: a 403 confirms the page exists and that someone else may
    use it, which is information a tenant has no use for."""
    client, _business_id = shop
    assert client.get('/billing/admin/payments').status_code == 404


def test_no_platform_admins_configured_means_nobody_qualifies(shop, monkeypatch):
    """A blank environment variable must not read as "everyone"."""
    monkeypatch.delenv('PLATFORM_ADMIN_EMAILS', raising=False)
    from auth.models import User
    _client, business_id = shop
    assert not providers.is_platform_admin(User.query.filter_by(business_id=business_id).first())


# --- confirming -------------------------------------------------------------

def test_confirming_activates_the_plan(platform_admin):
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()

    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': 'seen on statement'}, follow_redirects=True)

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    assert PaymentTransaction.query.one().status == 'paid'
    assert subscription.status == 'active'
    assert subscription.plan.code == 'standard'
    assert limits.effective_plan(business_id).code == 'standard'
    assert limits.has_feature('credit_ledger', business_id)


def test_confirming_twice_does_not_buy_a_second_month(platform_admin):
    """The obvious human error here is a double click, and the obvious machine
    one is a webhook delivered twice."""
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()

    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)
    first = Subscription.query.filter_by(business_id=business_id).one().paid_through

    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)
    assert Subscription.query.filter_by(business_id=business_id).one().paid_through == first


def test_paying_early_adds_time_rather_than_replacing_it(platform_admin):
    """Renewing a week before expiry must not throw that week away."""
    client, business_id = platform_admin
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.status = 'active'
    subscription.paid_through = datetime.datetime.utcnow() + datetime.timedelta(days=10)
    db.session.commit()
    existing = subscription.paid_through

    claim(client, reference='MP-EARLY')
    transaction = PaymentTransaction.query.filter_by(provider_ref='MP-EARLY').one()
    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)

    extended = Subscription.query.filter_by(business_id=business_id).one().paid_through
    assert extended > existing + datetime.timedelta(days=29)


def test_a_confirmation_is_audited(platform_admin):
    """Money moved because a person said so, and whose word it was has to be
    answerable later."""
    from auth.models import AuditLog
    client, _business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()
    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': 'matched'}, follow_redirects=True)

    entry = AuditLog.query.filter_by(action='billing.payment_confirmed').one()
    assert 'MP260805.1423.A1' in entry.details_json
    assert 'standard' in entry.details_json


def test_rejecting_keeps_the_claim_on_record(platform_admin):
    """A rejected claim is the record of someone saying money arrived when it
    did not, which is exactly the history worth keeping."""
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()

    client.post(f'/billing/admin/payments/{transaction.id}/reject',
                data={'reason': 'no such transaction'}, follow_redirects=True)

    assert PaymentTransaction.query.one().status == 'rejected'
    assert Subscription.query.filter_by(business_id=business_id).one().status == 'trialing'


def test_a_confirmed_payment_cannot_be_rejected_afterwards(platform_admin):
    client, _business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()
    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)

    client.post(f'/billing/admin/payments/{transaction.id}/reject',
                data={'reason': 'changed my mind'}, follow_redirects=True)
    assert PaymentTransaction.query.one().status == 'paid'


def test_nothing_renews_itself(platform_admin):
    """Mobile money has no reusable authorisation in Ghana, so the app must
    never imply it will take money again on its own."""
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()
    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)

    assert Subscription.query.filter_by(business_id=business_id).one().auto_renew is False


# --- the seam Paystack will slot into ---------------------------------------

def test_the_manual_provider_never_confirms_on_its_own():
    provider = providers.ManualMomoProvider()
    confirmed, message = provider.verify(transaction=None, evidence='MP-ANYTHING')

    assert confirmed is False
    assert provider.automatic is False
    assert 'confirmation' in message.lower()
