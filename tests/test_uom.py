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


def test_cost_conversion_keeps_the_precision_the_division_produced(crate_product):
    """This test previously asserted 2.08, and that assertion was the bug (F-41).

    Rounding a *derived* per-unit cost to pesewas discards money on every unit
    of the line: 50/24 stored as 2.08 records 49.92 for a carton that cost 50.00.
    The column now holds six decimals and display quantises to two."""
    _client, _business_id, product = crate_product
    # 50 / 24 = 2.0833...
    per_unit = uom.cost_to_base(product, Decimal('50.00'), uom.PURCHASE)
    assert per_unit == Decimal('2.083333')
    # The point of keeping them: the carton total comes back whole.
    assert (per_unit * 24).quantize(Decimal('0.01')) == Decimal('50.00')


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


def test_a_posted_unit_cannot_change_what_an_order_line_means(crate_product):
    """This asserted the opposite until orders became pack-only.

    It used to post `order_unit=base` and expect 240 bottles stored unchanged,
    which was correct while the unit was the buyer's choice. It is not any more:
    a wholesaler does not restock in single bottles, so for a product that comes
    in crates the number typed is crates. 240 crates of 24 is 5,760 bottles.

    The value is still posted here deliberately - the point is that it is now
    ignored. Deriving the unit is a stronger guarantee than gating a control,
    because there is nothing left to post your way past.
    """
    client, _business_id, product = crate_product

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id),
        'items-0-quantity_ordered': '240',
        'items-0-order_unit': 'base',          # ignored
        'items-0-unit_cost': '48.00',
    }, follow_redirects=True)

    line = PurchaseOrderItem.query.one()
    assert line.quantity_ordered == 5760, 'the posted unit changed the line'
    assert line.unit_cost == Decimal('2.00')   # 48.00 a crate is 2.00 a bottle


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

def test_an_order_states_its_unit_rather_than_asking(crate_product, app):
    """There is no selector any more, and that is the point.

    A wholesaler does not restock in single bottles - stock arrives in crates
    and cartons - so an order for a product with a pack is placed in packs and
    there is nothing to choose. The unit is derived in purchases/routes.py and a
    posted value cannot change what a line means, which is a stronger guarantee
    than gating a control was.

    This test previously asserted `order_unit` appeared on a trial plan and not
    on Shop. That was a fair test of a feature-gated dropdown; the dropdown is
    gone, so it now asserts the unit is *shown* instead.
    """
    client, business_id, _product = crate_product

    body = client.get('/purchases/add').get_data(as_text=True)
    assert 'order_unit' not in body, 'the unit is a choice again'
    assert 'order-unit' in body, 'the line does not say which unit it is in'

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    # `paid_through` as well as the status. Without it `effective_plan` reads the
    # subscription as lapsed and falls back to Free, which has no purchase orders
    # at all - so this half of the test was fetching a redirect and asserting
    # `order_unit` was absent from it. True, and about nothing.
    subscription.paid_through = datetime.date.today() + datetime.timedelta(days=30)
    db.session.commit()

    # Shop still cannot convert, and still says what unit it is entering in.
    body = client.get('/purchases/add').get_data(as_text=True)
    assert 'order_unit' not in body, 'the unit is a choice again'
    assert 'order-unit' in body, 'the line does not say which unit it is in'


def test_without_the_feature_everything_entered_is_in_base_units(crate_product):
    """This test previously asserted the opposite, and the assertion was wrong.

    The template hides the unit selector when the business lacks
    uom_conversion, but the WTForms field defaults to 'purchase'. So a Shop
    customer typing 10 pieces submitted no unit at all and had it read as 10
    crates - 240 pieces into stock. The old test posted the unit by hand, which
    hid the real case, and justified it as "the server is the authority".

    The server is the authority, and its answer here has to be base units: a
    business that is not sold the conversion is never shown a way to mean
    crates, so any purchase unit reaching this route is a default or a forgery.
    """
    client, business_id, product = crate_product
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    subscription.paid_through = datetime.datetime.utcnow() + datetime.timedelta(days=30)
    db.session.commit()

    # No order_unit at all, exactly as the template posts it.
    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id), 'items-0-quantity_ordered': '10',
        'items-0-unit_cost': '2.00',
    }, follow_redirects=True)

    assert PurchaseOrderItem.query.one().quantity_ordered == 10


def test_without_the_feature_a_hand_posted_purchase_unit_is_ignored(crate_product):
    """Hiding a control is not enforcing anything. Posting the unit by hand must
    not buy the conversion the plan does not include."""
    client, business_id, product = crate_product
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    subscription.paid_through = datetime.datetime.utcnow() + datetime.timedelta(days=30)
    db.session.commit()

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(), 'expected_date': '',
        'items-0-product_id': str(product.id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'purchase', 'items-0-unit_cost': '48.00',
    }, follow_redirects=True)

    assert PurchaseOrderItem.query.one().quantity_ordered == 10


# --- F-41: a derived per-unit cost must not lose the money it divided --------

@pytest.mark.parametrize('carton_price,per_carton,cartons,expected_total', [
    ('48.00', 24, 10, '480.00'),      # divides exactly - was always fine
    ('1.00', 24, 100, '100.00'),      # recorded 96.00 before
    ('55.00', 12, 40, '2200.00'),     # recorded 2198.40 before
    ('24.00', 7, 50, '1200.00'),      # recorded 1200.50 before - over, not under
])
def test_a_converted_cost_still_totals_what_was_paid(crate_product, carton_price,
                                                     per_carton, cartons, expected_total):
    """Two decimals on a *derived* figure loses money on every unit of the line.
    The cedis are small; the consequence is not - this is the cost price behind
    every margin, and the number services/sourcing.py compares suppliers on."""
    _client, _business_id, product = crate_product
    product.units_per_purchase_uom = per_carton
    db.session.commit()

    per_unit = uom.cost_to_base(product, Decimal(carton_price), uom.PURCHASE)
    units = per_carton * cartons
    recorded = (per_unit * units).quantize(Decimal('0.01'))

    assert recorded == Decimal(expected_total), (
        f'{cartons} cartons at {carton_price} recorded {recorded}, not {expected_total}')


def test_a_cost_typed_in_base_units_is_not_given_invented_precision(crate_product):
    """Only the divided figure needs the room. A price typed per bottle is
    already exact, and six decimals there would invent precision nobody entered."""
    _client, _business_id, product = crate_product

    assert uom.cost_to_base(product, Decimal('2.005'), uom.BASE) == Decimal('2.01')
    assert uom.cost_to_base(product, Decimal('2.00'), uom.BASE) == Decimal('2.00')


def test_the_stored_cost_survives_a_round_trip_through_the_database(crate_product):
    """Numeric(10,2) would have truncated the extra places on write, so the
    column had to widen with the calculation."""
    from purchases.models import PurchaseOrderItem, PurchaseOrder

    _client, business_id, product = crate_product
    product.units_per_purchase_uom = 24
    db.session.commit()

    po = PurchaseOrder(business_id=business_id, order_date=TODAY, status='ordered')
    db.session.add(po)
    db.session.flush()
    db.session.add(PurchaseOrderItem(
        po_id=po.id, product_id=product.id, quantity_ordered=24,
        quantity_received=0, unit_cost=uom.cost_to_base(product, Decimal('1.00'), uom.PURCHASE)))
    db.session.commit()
    db.session.expire_all()

    stored = PurchaseOrderItem.query.one().unit_cost
    assert stored == Decimal('0.041667')
    assert (stored * 24).quantize(Decimal('0.01')) == Decimal('1.00')
