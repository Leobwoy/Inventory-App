"""Stock movement — F-06, F-11, F-12.

The regression that matters most: a sale used to decrement both the cached
quantity and the batches, while deleting a sale restored only the cache, so the
two diverged permanently after a single deletion.
"""
import datetime

import pytest

from extensions import db
from products.models import Product
from purchases.models import PurchaseOrder, StockBatch
from sales.models import Sale
from services import stock

TODAY = datetime.date.today()


@pytest.fixture
def business(register):
    _client, business_id = register()
    return business_id


def receive(client, po, item, qty, expiry=None, batch=''):
    return client.post(f'/purchases/receive/{po.id}', data={
        'received_date': TODAY.isoformat(),
        f'qty_{item.id}': str(qty),
        f'batch_{item.id}': batch,
        f'expiry_{item.id}': expiry.isoformat() if expiry else '',
    }, follow_redirects=True)


def sell(client, product, qty, price='3.00'):
    return client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0', 'customer_name': 'Walk-in',
        'items-0-product_id': str(product.id), 'items-0-quantity': str(qty),
        'items-0-price_at_sale': price,
    }, follow_redirects=True)


def in_step(product_id, business_id):
    """(cached, authoritative) — these must always be equal."""
    product = Product.query.get(product_id)
    return product.quantity_in_stock, stock.batch_total(product_id, business_id)


# --------------------------------------------------------------------- receipt

def test_partial_receipt_leaves_the_order_open(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=240)

    receive(client, po, item, 100)

    assert PurchaseOrder.query.get(po.id).status == 'partially_received'
    assert Product.query.get(product.id).quantity_in_stock == 100


def test_second_receipt_completes_the_order(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=240)

    receive(client, po, item, 100)
    receive(client, po, item, 140)

    assert PurchaseOrder.query.get(po.id).status == 'received'
    assert Product.query.get(product.id).quantity_in_stock == 240
    assert StockBatch.query.filter_by(product_id=product.id).count() == 2


def test_receipt_captures_batch_and_expiry(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product)
    expiry = TODAY + datetime.timedelta(days=30)

    receive(client, po, item, 50, expiry=expiry, batch='LOT-A')

    batch = StockBatch.query.filter_by(product_id=product.id).one()
    assert batch.batch_number == 'LOT-A'
    assert batch.expiry_date == expiry


def test_blank_batch_numbers_are_generated_uniquely(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=100)

    receive(client, po, item, 40)
    receive(client, po, item, 60)

    numbers = [b.batch_number for b in StockBatch.query.all()]
    assert len(set(numbers)) == 2


@pytest.mark.parametrize('payload,expected', [
    ({'qty': 9999}, 'only 100 outstanding'),
    ({'qty': 10, 'expiry': TODAY - datetime.timedelta(days=1)}, 'after the receipt date'),
    ({'qty': 0}, 'at least one line'),
])
def test_receipt_guards_reject_without_moving_stock(register, make_product, make_po,
                                                    payload, expected):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=100)

    response = receive(client, po, item, payload['qty'], expiry=payload.get('expiry'))

    assert expected in response.get_data(as_text=True)
    assert Product.query.get(product.id).quantity_in_stock == 0
    assert StockBatch.query.count() == 0


def test_future_receipt_date_rejected(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product)

    response = client.post(f'/purchases/receive/{po.id}', data={
        'received_date': (TODAY + datetime.timedelta(days=1)).isoformat(),
        f'qty_{item.id}': '10',
    }, follow_redirects=True)

    assert 'cannot be in the future' in response.get_data(as_text=True)
    assert StockBatch.query.count() == 0


# ------------------------------------------------------------------------ FEFO

def test_sale_draws_soonest_expiry_first(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=200)

    receive(client, po, item, 100, expiry=TODAY + datetime.timedelta(days=60))
    receive(client, po, item, 100, expiry=TODAY + datetime.timedelta(days=10))

    sell(client, product, 120)

    batches = StockBatch.query.filter_by(product_id=product.id).order_by(
        StockBatch.expiry_date).all()
    assert batches[0].quantity_remaining == 0     # the sooner one, emptied
    assert batches[1].quantity_remaining == 80


def test_undated_batches_are_used_last(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=200)

    receive(client, po, item, 100)                                        # no expiry
    receive(client, po, item, 100, expiry=TODAY + datetime.timedelta(days=5))

    sell(client, product, 50)

    dated = StockBatch.query.filter(StockBatch.expiry_date.isnot(None)).one()
    undated = StockBatch.query.filter(StockBatch.expiry_date.is_(None)).one()
    assert dated.quantity_remaining == 50
    assert undated.quantity_remaining == 100


# ------------------------------------------------------- the F-12 regression

def test_deleting_a_sale_keeps_cache_and_batches_in_step(register, make_product):
    client, business_id = register()
    product = make_product(business_id, stock=200)

    sell(client, product, 150)
    assert in_step(product.id, business_id) == (50, 50)

    sale_id = Sale.query.one().id
    client.post('/sales/bulk_action', data={'action': 'delete', 'sale_ids': [str(sale_id)]},
                follow_redirects=True)

    cached, authoritative = in_step(product.id, business_id)
    assert cached == authoritative == 200


def test_repeated_sell_and_void_cycles_do_not_drift(register, make_product):
    client, business_id = register()
    product = make_product(business_id, stock=200)

    for _ in range(5):
        sell(client, product, 40)
        sale_id = Sale.query.order_by(Sale.id.desc()).first().id
        client.post('/sales/bulk_action', data={'action': 'delete', 'sale_ids': [str(sale_id)]},
                    follow_redirects=True)

    assert in_step(product.id, business_id) == (200, 200)
    assert stock.find_drift(business_id) == []


def test_overselling_is_refused_without_mutating(register, make_product):
    client, business_id = register()
    product = make_product(business_id, stock=10)

    response = sell(client, product, 9999)

    assert 'Not enough stock' in response.get_data(as_text=True)
    assert in_step(product.id, business_id) == (10, 10)


# ----------------------------------------------------------- tenant scoping

def test_fefo_query_ignores_other_tenants(register, make_product, app):
    _client, business_a = register(name='Alpha', email='a@x.example.com')
    _other, business_b = register(name='Beta', email='b@x.example.com', c=app.test_client())
    product = make_product(business_a, stock=100)

    db.session.add(StockBatch(
        business_id=business_b, product_id=product.id, batch_number='FOREIGN',
        quantity_received=500, quantity_remaining=500, received_date=TODAY,
    ))
    db.session.commit()

    visible = stock.available_batches(product.id, business_a)
    assert all(b.batch_number != 'FOREIGN' for b in visible)
    assert stock.batch_total(product.id, business_a) == 100


# ------------------------------------------------------------- reconciliation

def test_reconcile_detects_and_repairs_drift(register, make_product):
    _client, business_id = register()
    product = make_product(business_id, stock=100)

    Product.query.get(product.id).quantity_in_stock = 9999
    db.session.commit()

    drift = stock.find_drift(business_id)
    assert len(drift) == 1
    assert drift[0][1:] == (9999, 100)

    stock.reconcile(business_id)
    db.session.commit()

    assert Product.query.get(product.id).quantity_in_stock == 100
    assert stock.find_drift(business_id) == []


def test_po_lines_cannot_exist_without_a_product():
    """The receive route guards against item.product being None.

    That guard is defensive only: product_id is NOT NULL on purchase_order_item,
    and the foreign key blocks deleting a product a line still references, so the
    state cannot be constructed. Asserting the constraint is the honest test -
    if it is ever relaxed, the guard becomes load-bearing.
    """
    from purchases.models import PurchaseOrderItem
    assert PurchaseOrderItem.product_id.nullable is False
