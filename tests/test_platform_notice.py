"""A decision made in the console reaches the business it was made about.

Approving or rejecting a payment changed the plan and told the business
nothing. It went to the activity log, which answers "what happened to this
account" months later and is no use at all to somebody opening the app on
Monday wondering why their plan changed over the weekend.

Deliberately not an alert. `services/notifications.py` is derived, empties
itself, and its inbox is a paid feature - so a business that has just been
downgraded to Kiosk could not read the message explaining the downgrade. This
is stored, it does not become untrue, and it reaches every plan.
"""
import datetime

import pytest

from billing.models import BusinessNotice, PaymentTransaction, Plan, Subscription
from extensions import db
from services import notices

TODAY = datetime.date.today()


@pytest.fixture
def shop(register):
    client, business_id = register()
    return client, business_id


_ref = iter(range(1, 999))


def a_payment(business_id, amount=349):
    # provider_ref is globally unique - it is the reference somebody actually
    # sent - so a test raising several payments needs several of them.
    plan = Plan.query.filter_by(code='advanced').one()
    txn = PaymentTransaction(
        business_id=business_id, provider='momo',
        provider_ref='MM-%03d' % next(_ref),
        amount_ghs=amount, status='pending', plan_id=plan.id,
        period_start=TODAY, period_end=TODAY + datetime.timedelta(days=30))
    db.session.add(txn)
    db.session.commit()
    return txn


def test_a_confirmed_payment_leaves_a_message(shop):
    _client, business_id = shop
    notices.raise_for_payment(a_payment(business_id), 'confirm', 'admin@x.example.com')
    db.session.commit()

    notice = notices.unseen_for(business_id)
    assert notice is not None
    assert notice.level == 'success'
    assert '349.00' in notice.body


def test_a_rejected_payment_says_nothing_was_taken(shop):
    """The sentence somebody needs first when a payment is refused."""
    _client, business_id = shop
    notices.raise_for_payment(a_payment(business_id), 'reject', 'admin@x.example.com')
    db.session.commit()

    notice = notices.unseen_for(business_id)
    assert notice.level == 'danger'
    assert 'Nothing has been taken' in notice.body


def test_the_popup_reaches_the_page(shop):
    _client, business_id = shop
    notices.raise_for_payment(a_payment(business_id), 'confirm', 'a@x.example.com')
    db.session.commit()
    client, _ = shop

    page = client.get('/').get_data(as_text=True)

    assert 'id="platform-notice"' in page
    assert 'Payment received' in page


def test_it_reaches_a_business_on_the_free_plan(shop):
    """The case that makes this separate from the alerts inbox. A business
    downgraded to Kiosk cannot open that inbox - and is exactly the business
    that needs to be told why its plan changed."""
    client, business_id = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='free').one().id
    subscription.status = 'free'
    db.session.commit()
    notices.raise_for_payment(a_payment(business_id), 'reject', 'a@x.example.com')
    db.session.commit()

    assert 'Payment could not be confirmed' in client.get('/').get_data(as_text=True)


def test_closing_it_puts_it_away_for_good(shop):
    client, business_id = shop
    notices.raise_for_payment(a_payment(business_id), 'confirm', 'a@x.example.com')
    db.session.commit()
    notice = notices.unseen_for(business_id)

    client.post('/auth/notice/dismiss',
                data={'notice_id': notice.id, 'next': '/'}, follow_redirects=True)

    assert notices.unseen_for(business_id) is None
    assert 'id="platform-notice"' not in client.get('/').get_data(as_text=True)
    # Kept, not deleted, so the platform can tell a message that was read from
    # one that was never delivered.
    assert BusinessNotice.query.get(notice.id) is not None


def test_one_business_cannot_close_another_ones_message(shop, register, app):
    """The id arrives in a form, and a form is not evidence."""
    _client, business_id = shop
    notices.raise_for_payment(a_payment(business_id), 'confirm', 'a@x.example.com')
    db.session.commit()
    notice = notices.unseen_for(business_id)

    other, _other_id = register(name='Other Shop', email='other@x.example.com',
                                c=app.test_client())
    other.post('/auth/notice/dismiss', data={'notice_id': notice.id}, follow_redirects=True)

    assert notices.unseen_for(business_id) is not None, 'another tenant closed it'


def test_only_one_shows_at_a_time(shop):
    """Four modals stacked on a dashboard is not a message, it is an obstacle,
    and the person clicks through all of them without reading any."""
    client, business_id = shop
    for _ in range(3):
        notices.raise_for_payment(a_payment(business_id), 'confirm', 'a@x.example.com')
    db.session.commit()

    page = client.get('/').get_data(as_text=True)

    assert page.count('id="platform-notice"') == 1


# --- where "Got it" is allowed to send you ----------------------------------

@pytest.mark.parametrize('hostile', [
    '//evil.example.com',              # protocol-relative: absolute to a browser
    'https://evil.example.com',
    'http://evil.example.com/x',
    'javascript:alert(1)',
    'evil.example.com',
])
def test_the_dismiss_button_cannot_be_pointed_off_site(shop, hostile):
    """Reported by CodeQL against this exact route.

    The `next` field is posted, so it is attacker-controllable, and the first
    guard here was `target.startswith('/')` - which `//evil.com` satisfies while
    every browser reads it as absolute. A dismiss button that can be aimed
    anywhere is a phishing link with our domain on the front of it.
    """
    from auth.routes import _safe_next

    client, business_id = shop
    notices.raise_for_payment(a_payment(business_id), 'confirm', 'a@x.example.com')
    db.session.commit()
    notice = notices.unseen_for(business_id)

    with client.application.test_request_context():
        assert _safe_next(hostile) == '/'

    response = client.post('/auth/notice/dismiss',
                           data={'notice_id': notice.id, 'next': hostile})
    assert response.status_code == 302
    assert 'evil.example.com' not in response.headers['Location']
    assert 'javascript' not in response.headers['Location'].lower()


def test_a_real_page_is_still_where_you_land(shop):
    """The guard has to leave the ordinary case alone, or closing a message
    also moves you off the page you were reading."""
    from auth.routes import _safe_next

    client, _business_id = shop

    with client.application.test_request_context():
        assert _safe_next('/products/?page=2') == '/products/?page=2'
        assert _safe_next('/sales/add') == '/sales/add'
