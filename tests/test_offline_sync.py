"""Offline sale capture and sync — Stage 2.4c/2.4d.

A sale recorded without a signal is real money that exists only on one phone
until it syncs. Everything here protects one of three things:

- it is not lost (a server hiccup means retry, never discard),
- it is not doubled (a timeout after commit is indistinguishable from failure,
  so the device retries a sale that already landed),
- it is not quietly wrong (stock and price are re-decided on the server, and a
  conflict is reported to a person rather than resolved by a guess).
"""
import datetime
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from billing.models import Plan, Subscription
from credit.models import sale_total
from extensions import db
from products.models import Product
from sales.models import Customer, Sale

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    """A business on a plan that includes offline, with stock to sell."""
    client, business_id = register()
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml',
                           unit_price='10.00', cost_price='6.00', stock=100)
    return client, business_id, product


def csrf_headers(client):
    token = json.loads(client.get('/api/v1/session').data)['csrf_token']
    return {'X-CSRFToken': token, 'Content-Type': 'application/json'}


def queued(product, client_id='dev-1', quantity=2, price='10.00', **extra):
    payload = {
        'client_id': client_id,
        'sale_date': TODAY.isoformat(),
        'recorded_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'items': [{'product_id': product.id, 'quantity': quantity, 'price': price}],
        'amount_paid': '0',
        'payment_method': 'cash',
    }
    payload.update(extra)
    return payload


def sync(client, *sales):
    return client.post('/api/v1/sales', headers=csrf_headers(client),
                       data=json.dumps({'sales': list(sales)}))


# --- the catalogue the device sells from ------------------------------------

def test_the_catalogue_never_carries_cost_prices(shop):
    """The device cache is readable by anyone who picks the phone up, and cost
    price is gated everywhere else (F-16). Publishing it here would undo that."""
    client, _business_id, _product = shop

    body = client.get('/api/v1/catalogue').get_data(as_text=True)

    assert 'BelAqua' in body
    assert 'cost' not in body.lower()
    assert '6.00' not in body


def test_the_catalogue_stays_inside_the_business(shop, register, make_product):
    client, _business_id, _product = shop
    _other, other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    make_product(other_id, sku='KD-1', name='Kumasi Special Water')

    assert b'Kumasi Special' not in client.get('/api/v1/catalogue').data


# --- syncing works ----------------------------------------------------------

def test_a_queued_sale_is_recorded_and_draws_down_stock(shop):
    client, business_id, product = shop

    response = sync(client, queued(product, quantity=3))
    body = json.loads(response.data)

    assert response.status_code == 200
    assert body['accepted'] == 1
    assert body['results'][0]['status'] == 'accepted'

    sale = Sale.query.one()
    assert sale.client_id == 'dev-1'
    assert sale_total(sale) == Decimal('30.00')
    assert Product.query.get(product.id).quantity_in_stock == 97


def test_a_queued_sale_keeps_its_walk_in_details(shop):
    client, _business_id, product = shop
    sync(client, queued(product, customer_name='Kojo at Circle',
                        customer_phone='0244000111'))

    sale = Sale.query.one()
    assert sale.customer_name == 'Kojo at Circle'
    assert sale.buyer_phone == '0244000111'


def test_a_part_payment_taken_offline_is_recorded(shop):
    client, _business_id, product = shop
    sync(client, queued(product, quantity=2, amount_paid='15.00'))

    sale = Sale.query.one()
    assert sale_total(sale) == Decimal('20.00')
    assert sum(p.amount for p in sale.payments) == Decimal('15.00')


def test_a_backlog_syncs_in_one_request(shop):
    client, _business_id, product = shop
    body = json.loads(sync(client,
                           queued(product, 'dev-1', quantity=1),
                           queued(product, 'dev-2', quantity=2),
                           queued(product, 'dev-3', quantity=3)).data)

    assert body['accepted'] == 3
    assert Sale.query.count() == 3
    assert Product.query.get(product.id).quantity_in_stock == 94


# --- not doubled ------------------------------------------------------------

def test_syncing_the_same_sale_twice_records_it_once(shop):
    """A request that times out after the server committed looks exactly like
    one that failed, so the device retries. Without the device's own id, that
    retry sells the same crate twice."""
    client, _business_id, product = shop

    first = json.loads(sync(client, queued(product, quantity=3)).data)['results'][0]
    second = json.loads(sync(client, queued(product, quantity=3)).data)['results'][0]

    assert second['status'] == 'accepted'
    assert second.get('duplicate') is True
    assert second['sale_id'] == first['sale_id']
    assert Sale.query.count() == 1
    assert Product.query.get(product.id).quantity_in_stock == 97


def test_a_sale_with_no_client_id_is_refused(shop):
    """Without one there is no way to tell a retry from a second sale."""
    client, _business_id, product = shop
    payload = queued(product)
    payload['client_id'] = ''

    assert json.loads(sync(client, payload).data)['results'][0]['status'] == 'rejected'
    assert Sale.query.count() == 0


# --- not quietly wrong ------------------------------------------------------

def test_selling_more_than_is_left_is_a_conflict_not_a_silent_failure(shop):
    """Two tills selling the last crate is a real event. The person who can see
    the floor decides what happens, so the sale comes back with the numbers they
    need rather than disappearing."""
    client, _business_id, product = shop
    # Both, not just the cache: StockBatch is authoritative and deduct_fefo
    # reads it, so setting quantity_in_stock alone changes nothing (F-12).
    from purchases.models import StockBatch
    StockBatch.query.filter_by(product_id=product.id).update({'quantity_remaining': 2})
    product.quantity_in_stock = 2
    db.session.commit()

    result = json.loads(sync(client, queued(product, quantity=10)).data)['results'][0]

    assert result['status'] == 'conflict'
    assert result['reason'] == 'stock'
    assert result['wanted'] == 10
    assert result['product'] == 'BelAqua 750ml'
    assert Sale.query.count() == 0


def test_stock_never_goes_negative_when_two_devices_sell_the_last_one(shop):
    """The point of routing sync through services/stock.py rather than writing
    a second deduction path for the API."""
    client, _business_id, product = shop
    product.quantity_in_stock = 5
    from purchases.models import StockBatch
    StockBatch.query.filter_by(product_id=product.id).update({'quantity_remaining': 5})
    db.session.commit()

    body = json.loads(sync(client,
                           queued(product, 'phone-a', quantity=5),
                           queued(product, 'phone-b', quantity=5)).data)

    assert body['accepted'] == 1
    assert body['conflicts'] == 1
    assert Product.query.get(product.id).quantity_in_stock == 0


def test_a_price_the_device_offered_is_re_decided_on_the_server(shop):
    """The device was offline; the rule may have changed under it, and the price
    it cached may be stale. The server decides, exactly as it does for the form."""
    client, _business_id, product = shop

    # Discounting is off by default, so a below-list price must not go through
    # just because it arrived over the API instead of a form.
    result = json.loads(sync(client, queued(product, price='7.00')).data)['results'][0]

    assert result['status'] == 'conflict'
    assert result['reason'] == 'price'
    assert Sale.query.count() == 0


def test_a_discount_within_the_ceiling_syncs_and_is_recorded(shop):
    client, business_id, product = shop
    client.post('/auth/settings', data={
        'name': 'Accra Beverages', 'address': 'Accra', 'contact_number': '024',
        'expiry_alert_days': '30', 'max_discount_percent': '20',
    }, follow_redirects=True)

    assert json.loads(sync(client, queued(product, price='9.00')).data)['accepted'] == 1
    item = Sale.query.one().items[0]
    assert item.price_at_sale == Decimal('9.00')
    assert item.list_price == Decimal('10.00')


def test_a_product_deleted_while_offline_is_a_conflict(shop):
    client, _business_id, product = shop
    payload = queued(product)
    payload['items'][0]['product_id'] = 999999

    result = json.loads(sync(client, payload).data)['results'][0]
    assert result['status'] == 'conflict'
    assert result['reason'] == 'missing'


def test_a_future_dated_sale_is_refused(shop):
    client, _business_id, product = shop
    payload = queued(product)
    payload['sale_date'] = (TODAY + datetime.timedelta(days=1)).isoformat()

    assert json.loads(sync(client, payload).data)['results'][0]['status'] == 'rejected'


def test_one_bad_sale_does_not_take_down_the_batch(shop):
    """Each sale is its own transaction. Nineteen good ones must not roll back
    because the twentieth was malformed."""
    client, _business_id, product = shop
    bad = queued(product, 'dev-bad')
    bad['items'] = []

    body = json.loads(sync(client, queued(product, 'dev-1'), bad,
                           queued(product, 'dev-2')).data)

    assert body['accepted'] == 2
    assert Sale.query.count() == 2


def test_a_customer_from_another_business_is_refused(shop, register):
    """Never trust a posted foreign key, over the API least of all."""
    client, _business_id, product = shop
    _other, other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    theirs = Customer(business_id=other_id, name='Their Customer')
    db.session.add(theirs)
    db.session.commit()

    result = json.loads(sync(client, queued(product, customer_id=theirs.id)).data)['results'][0]
    assert result['status'] == 'rejected'
    assert Sale.query.count() == 0


# --- who may sync -----------------------------------------------------------

def test_the_api_answers_in_json_rather_than_redirecting(client):
    """A redirect to a login page hands the device HTML to parse as JSON, so it
    cannot tell being signed out from a sale that failed."""
    response = client.get('/api/v1/catalogue')

    assert response.status_code == 401
    assert response.is_json
    assert json.loads(response.data)['code'] == 'unauthenticated'


def test_a_plan_without_offline_is_told_so_in_json(shop):
    client, business_id, product = shop
    free = Plan.query.filter_by(code='free').first()
    Subscription.query.filter_by(business_id=business_id).update({'plan_id': free.id})
    db.session.commit()

    response = client.post('/api/v1/sales', headers=csrf_headers(client),
                           data=json.dumps({'sales': [queued(product)]}))

    assert response.status_code == 403
    assert json.loads(response.data)['code'] == 'feature_locked'


def test_staff_without_permission_to_sell_cannot_sync(shop, make_staff):
    _client, business_id, product = shop
    stock_staff = make_staff(business_id, 'Inventory Staff', 'kwesi@ab.example.com')

    response = stock_staff.post('/api/v1/sales',
                                headers={'Content-Type': 'application/json'},
                                data=json.dumps({'sales': [queued(product)]}))
    assert response.status_code in (400, 403)
    assert Sale.query.count() == 0


def test_a_sync_without_a_csrf_token_is_refused(shop, app):
    """The API is a state-changing POST like any other. It is exempt from the
    form, not from the protection.

    The suite runs with WTF_CSRF_ENABLED off, so this test turns it back on -
    without that it passes while proving nothing at all."""
    client, _business_id, product = shop
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        response = client.post('/api/v1/sales',
                               headers={'Content-Type': 'application/json'},
                               data=json.dumps({'sales': [queued(product)]}))
    finally:
        app.config['WTF_CSRF_ENABLED'] = False

    assert response.status_code == 400
    assert Sale.query.count() == 0


def test_an_oversized_batch_is_refused(shop):
    client, _business_id, product = shop
    many = [queued(product, f'dev-{n}') for n in range(60)]

    response = client.post('/api/v1/sales', headers=csrf_headers(client),
                           data=json.dumps({'sales': many}))
    assert response.status_code == 400
    assert Sale.query.count() == 0


def test_a_malformed_body_is_refused(shop):
    client, _business_id, _product = shop

    response = client.post('/api/v1/sales', headers=csrf_headers(client),
                           data=json.dumps({'not_sales': []}))
    assert response.status_code == 400


# --- the client side the page is responsible for ----------------------------

def test_the_sale_form_can_queue_when_the_plan_allows_it(shop):
    """Without the script loaded the form just fails offline and loses whatever
    was typed."""
    client, _business_id, _product = shop
    body = client.get('/sales/add').get_data(as_text=True)

    assert 'js/offline-sales.js' in body
    assert 'offline-notice' in body
    assert 'TrackTrackOffline' in body


def test_the_offline_script_is_not_served_to_a_plan_without_it(shop):
    client, business_id, _product = shop
    free = Plan.query.filter_by(code='free').first()
    Subscription.query.filter_by(business_id=business_id).update({'plan_id': free.id})
    db.session.commit()

    body = client.get('/sales/add').get_data(as_text=True)
    assert 'js/offline-sales.js' not in body


def test_the_pending_page_exists_for_the_badge_to_lead_to(shop):
    client, _business_id, _product = shop
    body = client.get('/sales/pending').get_data(as_text=True)

    assert 'Waiting to sync' in body
    assert 'not in your records yet' in body or 'not counted in any report' in body


def test_the_queue_never_discards_a_sale_the_server_did_not_confirm():
    """The one rule the client must not get wrong. A queued sale is the only
    copy that exists, so nothing removes it except the server saying it landed -
    not a network error, not a bad status, not a parse failure."""
    source = (Path(__file__).resolve().parent.parent / 'static' / 'js' / 'offline-sales.js')
    code = re.sub(r'/\*.*?\*/', '', source.read_text(encoding='utf-8'), flags=re.S)
    code = re.sub(r'//.*', '', code)

    sync_body = code.split('async sync()')[1].split('async announce()')[0]
    # Every early exit from sync() must return before reaching a removal.
    for guard in ["error: 'unreachable'", "error: 'signed-out'", "error: 'rejected'"]:
        assert guard in sync_body, f'{guard} path missing'
    removal = sync_body.split("if (result.status === 'accepted')")[1].split('}')[0]
    assert 'Offline.remove' in removal

    # A conflict is kept and marked, never deleted.
    conflict_branch = sync_body.split("result.status === 'conflict'")[1].split('}')[0]
    assert 'markConflict' in conflict_branch
    assert 'remove' not in conflict_branch


def test_every_queued_sale_gets_an_id_before_it_is_stored():
    """Without one, a retry after a timeout is indistinguishable from a second
    sale, and the same crate is sold twice."""
    source = (Path(__file__).resolve().parent.parent / 'static' / 'js' / 'offline-sales.js')
    code = source.read_text(encoding='utf-8')

    queue_body = code.split('async queue(sale)')[1].split('pending()')[0]
    assert 'client_id = sale.client_id || newId()' in queue_body
    # randomUUID is unavailable on http:// and older WebViews, so there must be
    # a fallback - an id is required, not best-effort.
    assert 'randomUUID' in code and 'Math.random' in code


def test_nan_and_infinity_are_refused(shop):
    """Decimal() accepts 'NaN' and 'Infinity' without raising. NaN poisons every
    comparison downstream; Infinity is the dangerous one, because
    min(received, total) clamps it to the full amount and would record a sale as
    paid in full when nothing was received."""
    client, _business_id, product = shop

    for bad in ('NaN', 'Infinity', '-Infinity', 'sNaN'):
        result = json.loads(sync(client, queued(product, f'price-{bad}', price=bad)).data)['results'][0]
        assert result['status'] == 'rejected', f'price {bad!r} was not refused'

        result = json.loads(sync(client, queued(product, f'paid-{bad}', amount_paid=bad)).data)['results'][0]
        assert result['status'] == 'rejected', f'amount_paid {bad!r} was not refused'

    assert Sale.query.count() == 0


def test_infinity_never_records_a_sale_as_settled(shop):
    """The specific failure the check exists to prevent."""
    client, _business_id, product = shop
    sync(client, queued(product, 'inf-pay', quantity=2, amount_paid='Infinity'))

    assert Sale.query.count() == 0
    from credit.models import Payment
    assert Payment.query.count() == 0


def test_the_queue_drains_past_a_conflict_in_a_full_batch():
    """A conflict is terminal - it drops out of the pending filter, so the queue
    head has moved. Requiring every sale to be accepted meant one refused sale
    in fifty stranded the other forty-nine until the next reconnect."""
    source = (Path(__file__).resolve().parent.parent / 'static' / 'js' / 'offline-sales.js')
    code = re.sub(r'//.*', '', re.sub(r'/\*.*?\*/', '', source.read_text(encoding='utf-8'), flags=re.S))

    sync_body = code.split('async sync()')[1].split('async announce()')[0]
    assert 'accepted + conflicts === sendable.length' in sync_body
    # 'retry' must still stop it, or a sale that cannot go spins forever.
    assert 'accepted === sendable.length' not in sync_body
