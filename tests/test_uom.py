"""Unit of measure conversion — Stage 2.1.

A wholesaler buys a crate of 24 and sells single bottles. Product carried
base_uom, purchase_uom and units_per_purchase_uom since the variant restructure
and nothing read them, so the arithmetic was left to whoever was typing.

Everything is stored in base units. These tests exist to keep that true: the
purchase unit may only appear at the edges, never in the database.
"""
import datetime
from decimal import Decimal

import pytest

from billing.models import Plan, Subscription
from extensions import db
from products.models import Product
from purchases.models import PurchaseOrderItem, StockBatch
from services import uom

TODAY = datetime.date.today()


@pytest.fixture
def crate_product(register, make_product):
    """Coca-Cola sold by the bottle, bought by the 24-bottle crate."""
    client, business_id = register()
    product = make_product(business_id, sku='COKE-350', name='Coca-Cola 350ml',
                           unit_price='5.00', cost_price='3.20')
    product.base_uom = 'bottles'
    product.purchase_uom = 'crates'
    product.units_per_purchase_uom = 24
    db.session.commit()
    return client, business_id, product


# ------------------------------------------------------------------ the maths

def test_factor_never_drops_below_one(make_product, register):
    _client, business_id = register()
    product = make_product(business_id)
    product.units_per_purchase_uom = 0
    assert uom.factor(product) == 1
    product.units_per_purchase_uom = None
    assert uom.factor(product) == 1


def test_conversion_only_applies_when_the_units_actually_differ(crate_product, make_product):
    _client, business_id, crate = crate_product
    assert uom.has_conversion(crate) is True

    # Same word for both units is not a conversion, whatever the factor says.
    plain = make_product(business_id, sku='PLAIN')
    plain.base_uom = plain.purchase_uom = 'pcs'
    plain.units_per_purchase_uom = 12
    assert uom.has_conversion(plain) is False


def test_to_base_multiplies_only_for_the_purchase_unit(crate_product):
    _client, _business_id, product = crate_product
    assert uom.to_base(product, 10, uom.PURCHASE) == 240
    assert uom.to_base(product, 10, uom.BASE) == 10


def test_split_keeps_the_remainder(crate_product):
    """A wholesaler genuinely holds part-crates; rounding would put the books out."""
    _client, _business_id, product = crate_product
    assert uom.split(product, 240) == (10, 0)
    assert uom.split(product, 250) == (10, 10)
    assert uom.split(product, 12) == (0, 12)


def test_describe_reads_the_way_a_person_would_say_it(crate_product):
    _client, _business_id, product = crate_product
    assert uom.describe(product, 240) == '10 crates (240 bottles)'
    assert uom.describe(product, 250) == '10 crates + 10 bottles (250 bottles)'
    assert uom.describe(product, 5) == '5 bottles'


def test_cost_converts_per_crate_to_per_bottle(crate_product):
    _client, _business_id, product = crate_product
    assert uom.cost_to_base(product, Decimal('48.00'), uom.PURCHASE) == Decimal('2.00')
    assert uom.cost_to_base(product, Decimal('2.00'), uom.BASE) == Decimal('2.00')


def test_cost_conversion_rounds_to_the_stored_precision(crate_product):
    """The column stores 2dp; anything finer would be discarded on write and make
    the total disagree with what was typed."""
    _client, _business_id, product = crate_product
    # 50 / 24 = 2.0833...
    assert uom.cost_to_base(product, Decimal('50.00'), uom.PURCHASE) == Decimal('2.08')


def test_cost_round_trips_back_to_the_crate_figure(crate_product):
    _client, _business_id, product = crate_product
    assert uom.cost_per_purchase_unit(product, Decimal('2.00')) == Decimal('48.00')


# ----------------------------------------------------------- ordering in crates

def test_ordering_in_crates_stores_base_units(crate_product):
    client, business_id, product = crate_product

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id),
        'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'purchase',
        'items-0-unit_cost': '48.00',
    }, follow_redirects=True)

    line = PurchaseOrderItem.query.one()
    assert line.quantity_ordered == 240              # not 10
    assert line.unit_cost == Decimal('2.00')         # not 48.00


def test_ordering_in_base_units_is_stored_unchanged(crate_product):
    client, _business_id, product = crate_product

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id),
        'items-0-quantity_ordered': '240',
        'items-0-order_unit': 'base',
        'items-0-unit_cost': '2.00',
    }, follow_redirects=True)

    line = PurchaseOrderItem.query.one()
    assert line.quantity_ordered == 240
    assert line.unit_cost == Decimal('2.00')


def test_a_product_without_a_conversion_ignores_the_unit_choice(register, make_product):
    """Posting 'purchase' for a product with no conversion must not multiply."""
    client, business_id = register()
    product = make_product(business_id, sku='SINGLE')     # pcs / pcs / 1

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id),
        'items-0-quantity_ordered': '100',
        'items-0-order_unit': 'purchase',
        'items-0-unit_cost': '2.00',
    }, follow_redirects=True)

    assert PurchaseOrderItem.query.one().quantity_ordered == 100


# ---------------------------------------------------------- receiving in crates

def test_receiving_in_crates_converts_to_stock_units(crate_product):
    client, business_id, product = crate_product
    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'purchase', 'items-0-unit_cost': '48.00',
    }, follow_redirects=True)
    line = PurchaseOrderItem.query.one()

    client.post(f'/purchases/receive/{line.po_id}', data={
        'received_date': TODAY.isoformat(),
        f'qty_{line.id}': '4', f'unit_{line.id}': 'purchase',
        f'batch_{line.id}': '', f'expiry_{line.id}': '',
    }, follow_redirects=True)

    assert PurchaseOrderItem.query.one().quantity_received == 96      # 4 x 24
    assert Product.query.get(product.id).quantity_in_stock == 96
    assert StockBatch.query.one().quantity_received == 96


def test_over_receipt_is_measured_in_base_units(crate_product):
    """Ordering 10 crates and receiving 11 must be caught, not silently accepted."""
    client, _business_id, product = crate_product
    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'purchase', 'items-0-unit_cost': '48.00',
    }, follow_redirects=True)
    line = PurchaseOrderItem.query.one()

    response = client.post(f'/purchases/receive/{line.po_id}', data={
        'received_date': TODAY.isoformat(),
        f'qty_{line.id}': '11', f'unit_{line.id}': 'purchase',
    }, follow_redirects=True)

    body = response.get_data(as_text=True)
    assert 'cannot receive' in body
    assert '264 bottles' in body            # 11 crates, named in stock units
    assert StockBatch.query.count() == 0


def test_partial_crate_receipt_is_allowed(crate_product):
    """Suppliers short-ship. 9 crates plus 6 loose bottles is a real delivery."""
    client, business_id, product = crate_product
    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'purchase', 'items-0-unit_cost': '48.00',
    }, follow_redirects=True)
    line = PurchaseOrderItem.query.one()

    client.post(f'/purchases/receive/{line.po_id}', data={
        'received_date': TODAY.isoformat(),
        f'qty_{line.id}': '222', f'unit_{line.id}': 'base',
    }, follow_redirects=True)

    assert Product.query.get(product.id).quantity_in_stock == 222
    assert uom.describe(product, 222) == '9 crates + 6 bottles (222 bottles)'


# ------------------------------------------------------------------ the feature

def test_the_selector_is_a_paid_feature(crate_product, app):
    """Conversion is a Depot-tier capability; Shop enters everything in units."""
    client, business_id, _product = crate_product

    body = client.get('/purchases/add').get_data(as_text=True)
    assert 'order_unit' in body                       # trial includes it

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    db.session.commit()

    body = client.get('/purchases/add').get_data(as_text=True)
    assert 'order_unit' not in body


def test_without_the_feature_a_posted_unit_is_still_honoured_server_side(crate_product):
    """The selector is hidden, not the conversion - a Shop customer who posts a
    unit by hand gets the same arithmetic, because the server is the authority
    and silently storing 10 bottles as 10 crates would corrupt their stock."""
    client, business_id, product = crate_product
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    db.session.commit()

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'purchase', 'items-0-unit_cost': '48.00',
    }, follow_redirects=True)

    assert PurchaseOrderItem.query.one().quantity_ordered == 240
