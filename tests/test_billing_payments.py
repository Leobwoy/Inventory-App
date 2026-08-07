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
from pathlib import Path

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
    cannot be gated on a permission - they would simply grant it to themselves.

    404 rather than 403: a 403 confirms the page exists and that someone else
    may use it, which is information a tenant has no use for."""
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
    assert extended >= existing + datetime.timedelta(days=billing_service.MONTH_DAYS)


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


def test_the_platform_admin_sees_the_link_and_a_tenant_does_not(shop, monkeypatch):
    """How the one platform admin actually reaches the screen: they log in like
    anyone else, and the link appears because their email is in the variable."""
    client, business_id = shop
    from auth.models import User
    email = User.query.filter_by(business_id=business_id).first().email

    monkeypatch.delenv('PLATFORM_ADMIN_EMAILS', raising=False)
    assert '/billing/admin/payments' not in client.get('/').get_data(as_text=True)

    monkeypatch.setenv('PLATFORM_ADMIN_EMAILS', email)
    body = client.get('/').get_data(as_text=True)
    assert '/billing/admin/payments' in body
    assert 'Confirm payments' in body
    assert client.get('/billing/admin/payments').status_code == 200


def test_the_email_match_ignores_case_and_spacing(shop, monkeypatch):
    """A comma-separated list typed into a hosting dashboard will have stray
    spaces and capitals in it, and failing closed on that would lock the only
    platform admin out of their own confirmation screen."""
    client, business_id = shop
    from auth.models import User
    email = User.query.filter_by(business_id=business_id).first().email

    monkeypatch.setenv('PLATFORM_ADMIN_EMAILS', f'  {email.upper()} , someone@else.com ')
    assert client.get('/billing/admin/payments').status_code == 200


# --- what the review round found ---------------------------------------------

def test_the_plan_is_read_from_the_transaction_not_from_todays_price(platform_admin):
    """confirm() used to recover the plan by matching the recorded amount against
    current prices. That breaks the first time a price moves: a customer who paid
    GHS 199 for Depot and is confirmed after Depot rises to GHS 249 matches no
    plan at all, and gets an error instead of the thing they paid for."""
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()
    assert transaction.plan_id is not None

    # The price list moves between claiming and confirming.
    depot = Plan.query.filter_by(code='standard').one()
    depot.price_monthly_ghs = Decimal('249.00')
    db.session.commit()

    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    assert subscription.plan.code == 'standard'
    assert subscription.status == 'active'
    # Charged what was agreed, not what the plan costs now.
    assert PaymentTransaction.query.one().amount_ghs == Decimal('199.00')


def test_a_rejected_payment_cannot_then_be_confirmed(platform_admin):
    """Guarding only against 'paid' left a rejected claim confirmable - so
    refusing a fraudulent payment and then confirming it by mistake would grant
    the plan anyway."""
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()

    client.post(f'/billing/admin/payments/{transaction.id}/reject',
                data={'reason': 'no such transaction'}, follow_redirects=True)
    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)

    assert PaymentTransaction.query.one().status == 'rejected'
    assert Subscription.query.filter_by(business_id=business_id).one().status == 'trialing'


def test_a_reference_that_is_mostly_spaces_is_refused(shop):
    """Length runs before the strip, so '  ab  ' satisfies a four-character
    minimum and is stored as two."""
    client, _business_id = shop
    response = client.post('/billing/upgrade/standard', data={
        'cycle': 'monthly', 'reference': '  ab  ', 'payer_note': '',
    }, follow_redirects=True)

    assert 'does not look like a transaction ID' in response.get_data(as_text=True)
    assert PaymentTransaction.query.count() == 0


def test_a_cycle_the_plan_has_no_price_for_is_refused(shop):
    """The radio hides it, but hiding a control is not enforcing anything."""
    client, _business_id = shop
    depot = Plan.query.filter_by(code='standard').one()
    depot.price_annual_ghs = None
    db.session.commit()

    response = client.post('/billing/upgrade/standard', data={
        'cycle': 'annual', 'reference': 'MP-NO-ANNUAL', 'payer_note': '',
    }, follow_redirects=True)

    assert 'not available for this plan' in response.get_data(as_text=True)
    assert PaymentTransaction.query.count() == 0


def test_the_current_plan_can_be_renewed(platform_admin):
    """Mobile money cannot charge anyone automatically, so renewing is the most
    common thing a paying customer comes to this page to do. Hiding the button
    on the plan they are already on hid exactly that."""
    client, business_id = platform_admin
    claim(client)
    transaction = PaymentTransaction.query.one()
    client.post(f'/billing/admin/payments/{transaction.id}/confirm',
                data={'note': ''}, follow_redirects=True)

    body = client.get('/billing/').get_data(as_text=True)
    assert 'Renew' in body
    assert url_for_upgrade('standard') in body


def url_for_upgrade(code):
    return f'/billing/upgrade/{code}'


def test_the_upgrade_page_carries_both_prices_for_the_amount_to_follow():
    """The amount shown is what the customer is about to send from their phone.
    Leaving it on the monthly figure while Annual is selected is not cosmetic -
    it tells someone to send the wrong money."""
    source = (Path(__file__).resolve().parent.parent
              / 'templates' / 'billing' / 'upgrade.html').read_text(encoding='utf-8')

    assert 'data-monthly=' in source and 'data-annual=' in source
    assert "input[name=\"cycle\"]" in source
    assert 'due.dataset[radio.value]' in source


def test_a_stale_in_memory_transaction_cannot_be_confirmed_twice(platform_admin, app):
    """Two independent sessions, which is the realistic version of the race.

    A second request loads the transaction, someone confirms it from the first,
    and the second request then acts on an object that says 'pending' while the
    row no longer does. confirm() re-reads it under a lock for exactly this, so
    the second attempt must find it settled and refuse rather than granting a
    second month.
    """
    from sqlalchemy.orm import Session

    client, business_id = platform_admin
    claim(client)
    transaction_id = PaymentTransaction.query.one().id

    first = Session(bind=db.engine)
    second = Session(bind=db.engine)
    try:
        # Both sessions read the row while it is still pending.
        stale = second.get(PaymentTransaction, transaction_id)
        assert stale.status == 'pending'

        # The first confirms and commits.
        client.post(f'/billing/admin/payments/{transaction_id}/confirm',
                    data={'note': ''}, follow_redirects=True)
        after_first = Subscription.query.filter_by(business_id=business_id).one().paid_through

        # The second acts on what it read, which is now out of date.
        db.session.expire_all()
        again = billing_service.confirm(
            PaymentTransaction.query.get(transaction_id),
            confirmed_by='second-request')
        db.session.commit()

        assert again is False, 'a settled transaction was confirmed a second time'
        assert Subscription.query.filter_by(business_id=business_id).one().paid_through == after_first
    finally:
        first.close()
        second.close()


def test_confirming_takes_a_lock_before_reading_the_period():
    """Extending paid_through is read-then-write on a shared row (invariant 8).
    Without the lock two confirmations landing together both extend from the
    same starting point, and one customer's paid month disappears."""
    import re
    source = (Path(__file__).resolve().parent.parent
              / 'services' / 'billing.py').read_text(encoding='utf-8')
    body = source.split('def confirm(')[1].split('def reject(')[0]
    body = re.sub(r'#.*', '', body)

    assert body.count('with_for_update()') == 2, (
        'both the subscription and the transaction must be locked')
    assert body.index('with_for_update()') < body.index('_extend_from(subscription)')
