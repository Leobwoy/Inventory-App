"""Stage W2 — the carton is what you type.

Stage U gave a pack a price of its own, beside the single price. That was still
backwards, and the user said so:

    "The main unit of measurement here should be the carton. We don't care what
    a single bottle costs, because different retailers charge different prices
    for the same bottle - one shop sells it at 3.00 and the next at 3.50. What
    we care about is the carton."

So the form asks for the carton and the route divides. `unit_price` and
`cost_price` stay stored, stay NOT NULL and are still what price sorting, the
offline catalogue and every report read - they simply stop being typed.

These tests are about the boundary in both directions: what a typed carton
figure becomes in the database, and what the database gives back when the same
product is opened for editing.
"""
from decimal import Decimal

import pytest

from extensions import db
from products.models import Product
from services import uom


CARTON = {
    'base_uom': 'bottle', 'purchase_uom': 'carton', 'units_per_purchase_uom': '24',
    'sell_unit': 'both', 'pack_price': '1050.00', 'pack_cost': '921.60',
}
LOOSE = {
    'base_uom': 'pcs', 'purchase_uom': '', 'units_per_purchase_uom': '1',
    'sell_unit': 'base', 'unit_price': '3.00', 'cost_price': '2.00',
}


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    # Only for its brand and item group: every product below is created through
    # the form, because the form is what this stage changed.
    seed = make_product(business_id, sku='SEED-1', name='Seed')
    return client, business_id, seed


def post_product(client, seed, extra, path='/products/add'):
    data = {
        'name': 'Club Beer 330ml', 'sku': '', 'category_id': '0',
        'brand_id': str(seed.brand_id), 'item_group_id': str(seed.item_group_id),
        'min_stock_alert': '0', 'quantity_in_stock': '0',
    }
    data.update(extra)
    return client.post(path, data=data, follow_redirects=True)


def saved(business_id, name='Club Beer 330ml'):
    return Product.query.filter_by(business_id=business_id, name=name).one()


# --- what a typed carton price becomes --------------------------------------

def test_a_carton_of_24_at_1050_stores_43_75_a_bottle(shop):
    """The arithmetic the owner never has to do, in the direction they never
    have to think about."""
    client, business_id, seed = shop

    post_product(client, seed, CARTON)

    product = saved(business_id)
    assert product.pack_price == Decimal('1050.00'), 'the typed price is stored as typed'
    assert product.unit_price == Decimal('43.75'), 'the per-bottle figure is derived'
    assert uom.price_for(product, uom.PURCHASE) == Decimal('1050.00')
    assert uom.price_for(product, uom.BASE) == Decimal('43.75')


def test_the_cost_keeps_enough_decimals_to_come_back_unchanged(shop):
    """A carton at 1,000 for 24 is 41.666... a bottle. Stored at two decimals it
    reads back as a carton costing 1,000.08, so every open-and-save of the
    product would walk its cost upwards. The column holds six."""
    client, business_id, seed = shop

    post_product(client, seed, dict(CARTON, pack_cost='1000.00'))

    product = saved(business_id)
    assert product.cost_price == Decimal('41.666667')
    assert uom.cost_per_purchase_unit(product, product.cost_price) == Decimal('1000.00')


def test_reopening_a_product_offers_back_the_carton_figures(shop):
    """What you typed is what you see. The form asks in cartons, so it must
    answer in cartons - the stored per-bottle cost multiplied back."""
    client, business_id, seed = shop
    post_product(client, seed, dict(CARTON, pack_cost='1000.00'))
    product = saved(business_id)

    page = client.get('/products/edit/%d' % product.id).get_data(as_text=True)

    assert 'value="1050.00"' in page, 'the carton price did not come back'
    assert 'value="1000.00"' in page, 'the carton cost came back drifted'


# --- the threshold is counted in the same unit as the stock ------------------

def test_a_low_stock_warning_is_typed_in_cartons(shop):
    """Somebody watching 5 cartons should type 5, not 120."""
    client, business_id, seed = shop

    post_product(client, seed, dict(CARTON, min_stock_alert='5'))

    assert saved(business_id).min_stock_alert == 120


def test_the_threshold_rounds_up_and_then_holds_still(shop):
    """100 bottles is 4.17 cartons. Rounding down would show 4, save 96, then
    show 4 again - walking the warning level down every time the product was
    opened. Up is both stable and the safe direction for a warning."""
    client, business_id, seed = shop
    post_product(client, seed, CARTON)
    product = saved(business_id)
    product.min_stock_alert = 100
    db.session.commit()

    page = client.get('/products/edit/%d' % product.id).get_data(as_text=True)
    assert 'value="5"' in page

    post_product(client, seed, dict(CARTON, min_stock_alert='5'),
                 path='/products/edit/%d' % product.id)
    assert saved(business_id).min_stock_alert == 120

    post_product(client, seed, dict(CARTON, min_stock_alert='5'),
                 path='/products/edit/%d' % product.id)
    assert saved(business_id).min_stock_alert == 120, 'the threshold moved on its own'


# --- loose goods are still sellable -----------------------------------------

def test_a_product_with_no_pack_is_still_priced_by_the_single(shop):
    client, business_id, seed = shop

    post_product(client, seed, LOOSE)

    product = saved(business_id)
    assert product.unit_price == Decimal('3.00')
    assert product.cost_price == Decimal('2.00')
    assert product.pack_price is None, 'a product with no pack has no pack price'
    assert uom.sell_units(product) == [uom.BASE]


def test_a_pack_price_does_not_linger_when_the_pack_is_removed(shop):
    """Inert while it lingers - uom.price_for gates on has_conversion - but it
    would come back to life the day someone re-added the pack."""
    client, business_id, seed = shop
    post_product(client, seed, CARTON)
    product = saved(business_id)

    post_product(client, seed, LOOSE, path='/products/edit/%d' % product.id)

    assert saved(business_id).pack_price is None


# --- the form asks for the unit it is actually sold in -----------------------

def test_a_packed_product_cannot_be_saved_without_a_carton_price(shop):
    client, business_id, seed = shop
    without = dict(CARTON)
    del without['pack_price']

    page = post_product(client, seed, without).get_data(as_text=True)

    assert 'Enter what one carton sells for.' in page
    assert Product.query.filter_by(business_id=business_id,
                                   name='Club Beer 330ml').count() == 0


def test_a_loose_product_is_asked_for_a_single_price_instead(shop):
    """The other half of the same rule. Demanding a carton price from a product
    that has no carton would make loose goods unsaveable."""
    client, business_id, seed = shop
    without = dict(LOOSE)
    del without['unit_price']

    page = post_product(client, seed, without).get_data(as_text=True)

    assert 'Enter what one pcs sells for.' in page
    assert 'Enter what one carton sells for.' not in page


def test_a_price_of_zero_is_still_savable(shop):
    """InputRequired, not DataRequired, is the rule this form already follows:
    DataRequired treats 0 as missing, and a free line has to be enterable."""
    client, business_id, seed = shop

    post_product(client, seed, dict(CARTON, pack_price='0'))

    assert saved(business_id).pack_price == Decimal('0')


# --- the whole chain, from the form to what the customer pays ----------------

def stock_up(product, quantity):
    import datetime
    from purchases.models import StockBatch
    db.session.add(StockBatch(
        business_id=product.business_id, product_id=product.id,
        batch_number='%s-SEED' % product.sku, quantity_received=quantity,
        quantity_remaining=quantity, received_date=datetime.date.today()))
    product.quantity_in_stock = quantity
    db.session.commit()


def sell(client, product, quantity, unit):
    import datetime
    return client.post('/sales/add', data={
        'sale_date': datetime.date.today().isoformat(), 'customer_id': '0',
        'items-0-product_id': str(product.id),
        'items-0-quantity': str(quantity),
        'items-0-sell_unit': unit, 'settlement': 'paid',
    }, follow_redirects=True)


def test_a_product_typed_in_cartons_sells_correctly_both_ways(shop):
    """The point of the whole stage, end to end. Nothing here builds a product
    by hand: it is created through the form exactly as an owner would, and then
    sold - because the risk of deriving a price on save is that the derived
    figure is the one the customer is billed."""
    from sales.models import SaleItem

    client, business_id, seed = shop
    post_product(client, seed, CARTON)
    product = saved(business_id)
    stock_up(product, 480)

    sell(client, product, 2, 'purchase')
    line = SaleItem.query.order_by(SaleItem.id.desc()).first()
    assert line.quantity == 48, 'two cartons should move 48 bottles'
    assert line.price_at_sale * line.quantity == Decimal('2100.000000')

    sell(client, product, 3, 'base')
    line = SaleItem.query.order_by(SaleItem.id.desc()).first()
    assert line.quantity == 3
    assert line.price_at_sale * line.quantity == Decimal('131.25'), \
        'a single bottle is priced from the carton it came out of'

    db.session.refresh(product)
    assert product.quantity_in_stock == 480 - 48 - 3


# --- who changed the price ---------------------------------------------------

def test_the_carton_price_is_what_gets_audited(shop):
    """Logging only unit_price would record a derived figure and miss the
    decision behind it - the number somebody actually typed."""
    import json
    from services.audit import AuditLog

    client, business_id, seed = shop
    post_product(client, seed, CARTON)
    product = saved(business_id)

    post_product(client, seed, dict(CARTON, pack_price='1120.00'),
                 path='/products/edit/%d' % product.id)

    logged = [json.loads(e.details_json)
              for e in AuditLog.query.filter_by(business_id=business_id,
                                                action='product.price_change')]
    fields = {entry['field']: entry for entry in logged}
    assert 'pack_price' in fields, 'the price that was typed was not recorded'
    assert fields['pack_price']['old'] == '1050.00'
    assert fields['pack_price']['new'] == '1120.00'
