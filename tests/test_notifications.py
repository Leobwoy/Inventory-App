"""What needs attention — Stage 2.5.

Alerts are derived, never stored. Every one is a fact about the current state of
the business, so it is computed on read and disappears when the fact stops being
true. There is no read/unread, because a stored alert can be dismissed while the
thing it warns about is still happening - and then the screen says everything is
fine while the stock is still at zero.

The other thing here is D1: expiry alerting is opt-in per item group. This
market sells mostly things that do not meaningfully expire, and warning about
all of it is how people learn to ignore warnings.
"""
import datetime
from decimal import Decimal

import pytest

from billing.models import Plan, Subscription
from extensions import db
from products.models import ItemGroup, Product
from purchases.models import StockBatch
from services import notifications

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    return client, business_id


def batch(business_id, product, expires_in_days, quantity=10):
    db.session.add(StockBatch(
        business_id=business_id, product_id=product.id,
        batch_number=f'B-{expires_in_days}',
        quantity_received=quantity, quantity_remaining=quantity,
        received_date=TODAY,
        expiry_date=TODAY + datetime.timedelta(days=expires_in_days)))
    db.session.commit()


def track_expiry(business_id, on=True):
    ItemGroup.query.filter_by(business_id=business_id).update({'track_expiry': on})
    db.session.commit()


# --- expiry is opt-in, per item group ---------------------------------------

def test_expiry_is_silent_until_a_group_asks_for_it(shop, make_product):
    """D1. A wholesaler of bottled water does not want to hear about expiry, and
    telling them anyway is how the one warning that mattered gets ignored with
    the rest."""
    _client, business_id = shop
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml')
    batch(business_id, product, expires_in_days=5)

    assert notifications.expiring_batches(business_id) == []

    track_expiry(business_id)
    assert len(notifications.expiring_batches(business_id)) == 1


def test_expired_stock_is_worse_than_expiring_stock(shop, make_product):
    """Already past its date and still in the FEFO queue, which means it goes to
    the next customer who buys that product."""
    _client, business_id = shop
    product = make_product(business_id, sku='YG-1', name='Yoghurt 500ml')
    track_expiry(business_id)
    batch(business_id, product, expires_in_days=-3)

    assert len(notifications.expired_batches(business_id)) == 1
    alerts = notifications.for_business(business_id)
    expired = next(a for a in alerts if a['kind'] == 'expired')
    assert expired['severity'] == 'critical'


def test_expired_stock_is_not_also_counted_as_expiring_soon(shop, make_product):
    """An expired batch is trivially "within the next 30 days" too, so without a
    lower bound the same crate is reported twice - once as critical and once as
    a warning - and the badge counts it twice. Two alerts, one problem, and the
    warning quietly says there is something else to sell first."""
    _client, business_id = shop
    product = make_product(business_id, sku='YG-1', name='Yoghurt 500ml')
    track_expiry(business_id)
    batch(business_id, product, expires_in_days=-3)

    assert len(notifications.expired_batches(business_id)) == 1
    assert notifications.expiring_batches(business_id) == []

    kinds = [a['kind'] for a in notifications.for_business(business_id)]
    assert 'expired' in kinds
    assert 'expiring' not in kinds


def test_a_batch_expiring_today_is_still_expiring_not_expired(shop, make_product):
    """The boundary the lower bound sits on. Today's date has not passed."""
    _client, business_id = shop
    product = make_product(business_id, sku='YG-1')
    track_expiry(business_id)
    batch(business_id, product, expires_in_days=0)

    assert len(notifications.expiring_batches(business_id)) == 1
    assert notifications.expired_batches(business_id) == []


def test_an_emptied_batch_stops_being_a_warning(shop, make_product):
    """Nothing is stored, so selling the stock removes the alert without anyone
    dismissing anything."""
    _client, business_id = shop
    product = make_product(business_id, sku='YG-1', name='Yoghurt 500ml')
    track_expiry(business_id)
    batch(business_id, product, expires_in_days=5)
    assert len(notifications.expiring_batches(business_id)) == 1

    StockBatch.query.filter_by(product_id=product.id).update({'quantity_remaining': 0})
    db.session.commit()

    assert notifications.expiring_batches(business_id) == []


def test_the_expiry_window_follows_the_business_setting(shop, make_product):
    """expiry_alert_days exists in Settings and had nothing reading it."""
    from auth.models import Business

    _client, business_id = shop
    product = make_product(business_id, sku='YG-1')
    track_expiry(business_id)
    batch(business_id, product, expires_in_days=20)

    business = db.session.get(Business, business_id)
    business.expiry_alert_days = 7
    db.session.commit()
    assert notifications.expiring_batches(business_id) == []

    business.expiry_alert_days = 30
    db.session.commit()
    assert len(notifications.expiring_batches(business_id)) == 1


# --- stock -------------------------------------------------------------------

def test_out_of_stock_is_separate_from_running_low(shop, make_product):
    """One is a warning; the other is already costing money. Folding them
    together loses exactly that distinction."""
    _client, business_id = shop
    empty = make_product(business_id, sku='E-1', name='Empty Item', stock=0)
    low = make_product(business_id, sku='L-1', name='Low Item', stock=3)
    fine = make_product(business_id, sku='F-1', name='Fine Item', stock=500)
    low.min_stock_alert = 10
    fine.min_stock_alert = 10
    db.session.commit()

    assert [p.id for p in notifications.out_of_stock(business_id)] == [empty.id]
    assert [p.id for p in notifications.low_stock(business_id)] == [low.id]

    severities = {a['kind']: a['severity'] for a in notifications.for_business(business_id)}
    assert severities['out_of_stock'] == 'critical'
    assert severities['low_stock'] == 'warning'


def test_a_deactivated_product_is_not_an_alert(shop, make_product):
    """Retired stock being at zero is the point of retiring it."""
    _client, business_id = shop
    product = make_product(business_id, sku='OLD-1', stock=0)
    product.is_active = False
    db.session.commit()

    assert notifications.out_of_stock(business_id) == []


def test_alerts_stay_inside_the_business(shop, register, make_product):
    _client, business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    make_product(other_id, sku='KD-1', name='Kumasi Special', stock=0)

    assert notifications.out_of_stock(business_id) == []
    assert notifications.for_business(business_id) == [] or all(
        'Kumasi' not in a['detail'] for a in notifications.for_business(business_id))


# --- ordering and the page ---------------------------------------------------

def test_the_worst_thing_is_listed_first(shop, make_product):
    """The list answers "what needs me today", so it cannot be ordered by which
    module happened to produce each item."""
    _client, business_id = shop
    empty = make_product(business_id, sku='E-1', name='Empty', stock=0)
    low = make_product(business_id, sku='L-1', name='Low', stock=2)
    low.min_stock_alert = 10
    db.session.commit()

    alerts = notifications.for_business(business_id)
    assert alerts[0]['severity'] == 'critical'
    assert [a['severity'] for a in alerts] == sorted(
        [a['severity'] for a in alerts],
        key=lambda s: notifications.SEVERITY_ORDER[s])


def test_the_page_says_so_when_nothing_is_wrong(shop):
    client, _business_id = shop
    body = client.get('/products/alerts').get_data(as_text=True)

    assert 'Nothing needs you right now' in body


def test_the_page_lists_what_is_wrong(shop, make_product):
    client, business_id = shop
    make_product(business_id, sku='E-1', name='Empty Item', stock=0)

    body = client.get('/products/alerts').get_data(as_text=True)
    assert 'out of stock' in body
    assert 'Empty Item' in body


def test_the_badge_count_is_a_separate_request(shop, make_product):
    """Not a context processor: working this out costs several queries, and the
    sidebar renders on every route in the app."""
    import json

    client, business_id = shop
    make_product(business_id, sku='E-1', stock=0)

    response = client.get('/products/alerts/count')
    body = json.loads(response.data)

    assert response.status_code == 200
    assert body['count'] >= 1
    assert body['critical'] >= 1
    # A live figure; a cached one is worse than none.
    assert response.headers['Cache-Control'] == 'no-store'


def test_the_sidebar_asks_for_the_count_rather_than_rendering_it(shop):
    client, _business_id = shop
    body = client.get('/').get_data(as_text=True)

    assert '/products/alerts' in body
    assert "fetch('/products/alerts/count'" in body


# --- the subscription reminders ----------------------------------------------

def test_a_trial_about_to_end_is_said_before_it_ends(shop):
    """Someone who discovers a downgrade by finding a feature gone does not come
    back; someone warned three days out has a decision to make."""
    _client, business_id = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.trial_ends_at = datetime.datetime.utcnow() + datetime.timedelta(days=2)
    db.session.commit()

    alerts = notifications.for_business(business_id)
    trial = next(a for a in alerts if a['kind'] == 'trial_ending')
    assert '2 days' in trial['title']
    assert trial['endpoint'] == 'billing.overview'


def test_a_trial_with_a_fortnight_left_is_not_nagged_about(shop):
    _client, business_id = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.trial_ends_at = datetime.datetime.utcnow() + datetime.timedelta(days=12)
    db.session.commit()

    assert not [a for a in notifications.for_business(business_id)
                if a['kind'] == 'trial_ending']


def test_a_paid_plan_running_out_is_flagged(shop):
    """Mobile money cannot renew on its own, so this one genuinely needs them."""
    _client, business_id = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.status = 'active'
    subscription.plan_id = Plan.query.filter_by(code='standard').one().id
    subscription.paid_through = datetime.datetime.utcnow() + datetime.timedelta(days=3)
    db.session.commit()

    alerts = notifications.for_business(business_id)
    assert any(a['kind'] == 'plan_ending' for a in alerts)


# --- an alert is only shown to someone allowed to see what it is about -------

def test_a_stock_clerk_is_not_shown_what_customers_owe(shop, make_staff, make_product):
    """The alerts page spans modules on purpose, and that walks it straight
    through two permission gates. Someone holding only products.view would
    otherwise read the total owed off a page they may open, having been refused
    the ledger it was computed from - and the alert even links them there."""
    from sales.models import Sale, SaleItem

    _client, business_id = shop
    product = make_product(business_id, sku='BA-750')
    long_ago = TODAY - datetime.timedelta(days=90)
    sale = Sale(business_id=business_id, sale_date=long_ago,
                customer_name='Mensah Stores')
    sale.items.append(SaleItem(product_id=product.id, quantity=10,
                               price_at_sale=Decimal('5.00'),
                               list_price=Decimal('5.00')))
    db.session.add(sale)
    db.session.commit()

    owner_sees = [a['kind'] for a in notifications.for_business(business_id)]
    assert 'overdue_credit' in owner_sees, 'the alert being withheld must exist'

    clerk = make_staff(business_id, 'Inventory Staff', 'clerk@ab.example.com',
                       permissions=['products.view'])
    body = clerk.get('/products/alerts').get_data(as_text=True)

    assert 'overdue' not in body.lower()
    assert 'outstanding' not in body.lower()


def test_a_stock_clerk_is_not_shown_how_long_the_plan_has_left(shop, make_staff):
    """Same gate, different page: billing is behind settings.manage."""
    _client, business_id = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.trial_ends_at = datetime.datetime.utcnow() + datetime.timedelta(days=2)
    db.session.commit()

    assert any(a['kind'] == 'trial_ending'
               for a in notifications.for_business(business_id))

    clerk = make_staff(business_id, 'Inventory Staff', 'clerk@ab.example.com',
                       permissions=['products.view'])
    body = clerk.get('/products/alerts').get_data(as_text=True)

    assert 'trial' not in body.lower()


def test_the_badge_counts_only_what_the_page_will_show(shop, make_staff):
    """A badge promising three things over a page showing two is a small bug of
    the kind nobody reports - they just stop believing the number."""
    import json

    _client, business_id = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.trial_ends_at = datetime.datetime.utcnow() + datetime.timedelta(days=2)
    db.session.commit()

    clerk = make_staff(business_id, 'Inventory Staff', 'clerk@ab.example.com',
                       permissions=['products.view'])
    counted = json.loads(clerk.get('/products/alerts/count').data)['count']

    # Nothing here is a stock problem, and the plan is not the clerk's business,
    # so the honest count is zero rather than "one you may not look at".
    assert counted == 0
    assert any(a['kind'] == 'trial_ending'
               for a in notifications.for_business(business_id))


def test_stock_alerts_still_reach_the_person_who_handles_stock(shop, make_staff,
                                                               make_product):
    """The filter withholds what is behind another gate, not everything."""
    _client, business_id = shop
    make_product(business_id, sku='E-1', name='Empty Item', stock=0)

    clerk = make_staff(business_id, 'Inventory Staff', 'clerk@ab.example.com',
                       permissions=['products.view'])
    body = clerk.get('/products/alerts').get_data(as_text=True)

    assert 'Empty Item' in body
    assert 'out of stock' in body
