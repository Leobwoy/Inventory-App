"""Selling by the carton — Stage U2, the sale path.

Every test here asserts **both the money and the stock**, because either can be
right while the other is wrong and that is the failure nobody would notice: a
carton billed correctly at 1,050 while only one bottle leaves the shelf reads as
a good day's trading right up until stocktake.

The rounding case is the one worth having. A carton at 1,000 for 24 is 41.666...
a bottle, and at two decimals 48 bottles bill 2,000.16 for what was agreed at
2,000.00. Sixteen pesewas is nothing; sixteen pesewas on every carton of every
sale is the F-41 defect again, on the side the customer actually pays.
"""
import datetime
import json
from decimal import Decimal

import pytest

from billing.models import Plan, Subscription
from extensions import db
from products.models import Product
from sales.models import Sale, SaleItem
from services import uom

TODAY = datetime.date.today()


@pytest.fixture
def carton_shop(register, make_product):
    """Club Beer: carton of 24, 1,050 a carton or 48 a bottle, 480 in stock."""
    client, business_id = register()
    product = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                           unit_price='48.00', cost_price='20.00', stock=480)
    product.base_uom = 'bottles'
    product.purchase_uom = 'carton'
    product.units_per_purchase_uom = 24
    product.pack_price = Decimal('1050.00')
    product.sell_unit = 'both'
    db.session.commit()
    return client, business_id, product


def sell(client, product, quantity, unit='base', price=None):
    data = {'sale_date': TODAY.isoformat(), 'customer_id': '0',
            'items-0-product_id': str(product.id),
            'items-0-quantity': str(quantity),
            'items-0-sell_unit': unit, 'settlement': 'paid'}
    if price is not None:
        data['items-0-price_at_sale'] = str(price)
    return client.post('/sales/add', data=data, follow_redirects=True)


def sync(client, product, quantity, unit, client_id, paid):
    """Post a queued sale the way a phone does - real endpoint, real CSRF."""
    token = json.loads(client.get('/api/v1/session').data)['csrf_token']
    return client.post('/api/v1/sales',
                       headers={'X-CSRFToken': token,
                                'Content-Type': 'application/json'},
                       data=json.dumps({'sales': [{
                           'client_id': client_id,
                           'sale_date': TODAY.isoformat(),
                           'recorded_at': datetime.datetime.utcnow().isoformat() + 'Z',
                           'items': [{'product_id': product.id,
                                      'quantity': quantity,
                                      'sell_unit': unit}],
                           'amount_paid': paid,
                           'payment_method': 'cash',
                       }]}))


def last_line():
    return SaleItem.query.order_by(SaleItem.id.desc()).first()


def line_total(item):
    return (Decimal(str(item.price_at_sale)) * item.quantity).quantize(Decimal('0.01'))


# --- the money and the stock, together ---------------------------------------

def test_two_cartons_bill_the_carton_price_and_move_the_bottles(carton_shop):
    client, _business_id, product = carton_shop
    before = product.quantity_in_stock

    sell(client, product, 2, uom.PURCHASE)

    item = last_line()
    assert line_total(item) == Decimal('2100.00'), 'two cartons at 1,050'
    db.session.expire_all()
    assert Product.query.get(product.id).quantity_in_stock == before - 48, \
        'the money was right but the shelf did not move'


def test_singles_still_bill_the_single_price(carton_shop):
    client, _business_id, product = carton_shop
    before = product.quantity_in_stock

    sell(client, product, 3, uom.BASE)

    item = last_line()
    assert line_total(item) == Decimal('144.00')      # 3 x 48
    db.session.expire_all()
    assert Product.query.get(product.id).quantity_in_stock == before - 3


def test_a_carton_is_cheaper_than_the_bottles_in_it(carton_shop):
    """The whole reason a shop buys a case. 1,050 against 24 x 48 = 1,152."""
    client, _business_id, product = carton_shop

    sell(client, product, 1, uom.PURCHASE)
    by_carton = line_total(last_line())
    sell(client, product, 24, uom.BASE)
    by_bottle = line_total(last_line())

    assert by_carton == Decimal('1050.00')
    assert by_bottle == Decimal('1152.00')
    assert by_carton < by_bottle


def test_a_pack_price_that_does_not_divide_evenly_still_bills_exactly(carton_shop):
    """1,000 for 24 is 41.666... a bottle. Stored at two decimals it would bill
    2,000.16 for two cartons; at six it bills 2,000.00. This is F-41 on the
    selling side, and the reason price_at_sale is Numeric(14, 6)."""
    client, _business_id, product = carton_shop
    product.pack_price = Decimal('1000.00')
    db.session.commit()

    sell(client, product, 2, uom.PURCHASE)

    assert line_total(last_line()) == Decimal('2000.00')


def test_the_line_remembers_what_was_rung_up(carton_shop):
    """So the invoice can say "2 cartons" rather than "48 bottles". Stored, not
    derived: a pack size can be corrected later and deriving quantity / factor
    at read time would silently rewrite an old sale."""
    client, _business_id, product = carton_shop

    sell(client, product, 2, uom.PURCHASE)

    item = last_line()
    assert item.quantity == 48
    assert item.sold_quantity == 2
    assert item.sell_unit == uom.PURCHASE
    assert item.sold_as == (2, 'carton')
    assert item.price_per_sold_unit == Decimal('1050.00')


def test_an_old_sale_is_not_rewritten_when_the_pack_size_changes(carton_shop):
    client, _business_id, product = carton_shop
    sell(client, product, 2, uom.PURCHASE)

    product.units_per_purchase_uom = 12          # corrected afterwards
    db.session.commit()
    db.session.expire_all()

    item = last_line()
    assert item.sold_as[0] == 2, 'the old sale now claims a different quantity'


# --- the gates ---------------------------------------------------------------

def test_a_plan_without_conversion_cannot_post_its_way_to_a_carton(carton_shop):
    """Hiding the selector enforces nothing. This project has already shipped
    one route that read a hand-posted unit the plan did not include."""
    client, business_id, product = carton_shop
    free = Plan.query.filter_by(code='free').first()
    Subscription.query.filter_by(business_id=business_id).update({'plan_id': free.id})
    db.session.commit()
    before = product.quantity_in_stock

    sell(client, product, 2, uom.PURCHASE)

    item = last_line()
    assert item.quantity == 2, 'the conversion was bought by posting for it'
    db.session.expire_all()
    assert Product.query.get(product.id).quantity_in_stock == before - 2


def test_a_product_sold_only_in_singles_refuses_a_carton(carton_shop):
    client, _business_id, product = carton_shop
    product.sell_unit = 'base'
    db.session.commit()
    before = product.quantity_in_stock

    sell(client, product, 2, uom.PURCHASE)

    assert last_line().quantity == 2
    db.session.expire_all()
    assert Product.query.get(product.id).quantity_in_stock == before - 2


def test_a_carton_may_not_be_sold_below_what_a_carton_cost(carton_shop):
    """The floor compares like with like. Cost is stored per bottle, so a naive
    comparison would measure a carton price against a bottle's cost and wave
    through a carton at 500 that cost 921.60."""
    client, business_id, product = carton_shop
    product.cost_price = Decimal('38.40')        # 921.60 a carton
    db.session.commit()
    from auth.models import Business
    Business.query.get(business_id).max_discount_percent = Decimal('50')
    db.session.commit()
    before = Sale.query.count()

    sell(client, product, 1, uom.PURCHASE, price='900.00')

    assert Sale.query.count() == before, 'a carton sold below what it cost'


def test_the_discount_ceiling_is_measured_on_the_carton(carton_shop):
    """A wholesaler negotiates over the carton, so 20% off means 20% off 1,050
    rather than 20% off a bottle multiplied up."""
    client, business_id, product = carton_shop
    from auth.models import Business
    Business.query.get(business_id).max_discount_percent = Decimal('20')
    db.session.commit()

    sell(client, product, 1, uom.PURCHASE, price='840.00')   # exactly 20% off

    assert line_total(last_line()) == Decimal('840.00')


# --- the offline queue -------------------------------------------------------

def test_a_sale_synced_from_a_phone_keeps_its_unit(carton_shop):
    """A queued sale can arrive days later. Without the unit it silently reverts
    to pieces, so two cartons become two bottles and the shelf is 46 out."""
    client, _business_id, product = carton_shop
    before = product.quantity_in_stock

    response = sync(client, product, 2, uom.PURCHASE, 'phone-1', '2100.00')

    assert response.status_code == 200, response.get_data(as_text=True)
    item = last_line()
    assert item.quantity == 48
    assert line_total(item) == Decimal('2100.00')
    db.session.expire_all()
    assert Product.query.get(product.id).quantity_in_stock == before - 48


def test_a_phone_cannot_post_its_way_to_a_unit_the_product_does_not_sell(carton_shop):
    """The reachable half of the API gate.

    The plan half is defensive rather than testable: `offline` and
    `uom_conversion` are both standard tier, so every plan that can sync at
    all also has conversion. It stays in the code because the two are
    separate features that share a tier today, not one feature - and a
    queued sale can arrive days after a downgrade.
    """
    client, _business_id, product = carton_shop
    product.sell_unit = 'base'
    db.session.commit()
    before = product.quantity_in_stock

    sync(client, product, 2, uom.PURCHASE, 'phone-2', '96.00')

    item = last_line()
    assert item.quantity == 2, (
        'a phone bought a carton the product is not sold by')
    db.session.expire_all()
    assert Product.query.get(product.id).quantity_in_stock == before - 2


def test_what_a_customer_owes_is_a_number_of_pesewas(carton_shop, register):
    """The other half of the widening, and the half no existing test covered.

    `price_at_sale` is Numeric(14, 6) so a pack price divided by its count stays
    exact. That precision must not escape into what someone is told they owe:
    the ageing report, the statement and the credit dashboard all read this sum,
    and 2,000.000016 is not an amount of money anybody hands over.
    """
    from services import credit as credit_service
    from sales.models import Customer

    client, business_id, product = carton_shop
    product.pack_price = Decimal('1000.00')      # 41.666... a bottle
    db.session.commit()

    customer = Customer(business_id=business_id, name='Mensah Stores')
    db.session.add(customer)
    db.session.commit()

    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': str(customer.id),
        'items-0-product_id': str(product.id), 'items-0-quantity': '2',
        'items-0-sell_unit': uom.PURCHASE, 'settlement': 'credit',
    }, follow_redirects=True)

    owed = credit_service.total_outstanding(business_id)

    assert owed == Decimal('2000.00')
    assert -owed.as_tuple().exponent <= 2, f'{owed} is not a number of pesewas'
