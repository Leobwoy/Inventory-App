"""Sale price authority — F-07.

price_at_sale used to be written straight from form data. readonly in the
template is a rendering hint; the value still posts.
"""
import datetime
import json
from decimal import Decimal

import pytest

from auth.models import AuditLog, Business, User
from extensions import db
from sales.models import SaleItem

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    """An Owner, a product listed at 3.00 costing 2.00, and plenty of stock."""
    client, business_id = register()
    product = make_product(business_id, unit_price='3.00', cost_price='2.00', stock=10_000)
    return client, business_id, product


def sell(client, product, price):
    return client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0', 'customer_name': 'W',
        'items-0-product_id': str(product.id), 'items-0-quantity': '1',
        'items-0-price_at_sale': str(price),
    }, follow_redirects=True)


def charged():
    item = SaleItem.query.order_by(SaleItem.id.desc()).first()
    return Decimal(item.price_at_sale) if item else None


def allow_discount(business_id, percent, user_email='owner@ab.example.com'):
    Business.query.get(business_id).max_discount_percent = Decimal(percent)
    db.session.commit()


def test_sale_at_list_price_is_recorded_normally(shop):
    client, _business_id, product = shop
    sell(client, product, '3.00')
    assert charged() == Decimal('3.00')


@pytest.mark.parametrize('bad_price', ['0.01', '0', '-5'])
def test_underpricing_is_refused_and_writes_nothing(register, make_product, make_staff, bad_price):
    """The original hole: any price could be posted."""
    _owner, business_id = register()
    product = make_product(business_id, unit_price='3.00', cost_price='2.00', stock=100)
    staff = make_staff(business_id, 'Sales Staff', 'sales@x.example.com')

    sell(staff, product, bad_price)

    assert SaleItem.query.count() == 0


def test_discount_needs_the_permission(register, make_product, make_staff):
    _owner, business_id = register()
    product = make_product(business_id, unit_price='3.00', cost_price='2.00', stock=100)
    allow_discount(business_id, 20)
    staff = make_staff(business_id, 'Sales Staff', 'sales@x.example.com')     # no sales.discount

    response = sell(staff, product, '2.70')

    assert 'do not have permission to sell below' in response.get_data(as_text=True)
    assert SaleItem.query.count() == 0


def test_permission_alone_is_not_enough_without_a_policy(register, make_product, make_staff):
    """max_discount_percent defaults to 0 - two independent gates."""
    _owner, business_id = register()
    product = make_product(business_id, unit_price='3.00', cost_price='2.00', stock=100)
    staff = make_staff(business_id, 'Sales Staff', 'sales@x.example.com',
                       permissions={'sales.view', 'sales.create', 'products.view', 'sales.discount'})

    response = sell(staff, product, '2.70')

    assert 'discounts are switched off' in response.get_data(as_text=True)
    assert SaleItem.query.count() == 0


def test_discount_within_the_ceiling_is_accepted(shop):
    client, business_id, product = shop
    allow_discount(business_id, 10)

    sell(client, product, '2.70')          # exactly 10% off

    assert charged() == Decimal('2.70')


def test_discount_beyond_the_ceiling_states_the_floor(shop):
    client, business_id, product = shop
    allow_discount(business_id, 10)

    response = sell(client, product, '2.50')
    body = response.get_data(as_text=True)

    assert 'most that may be discounted' in body
    assert '2.70' in body                   # tells them what is allowed


def test_never_below_cost_even_inside_the_ceiling(shop):
    client, business_id, product = shop
    allow_discount(business_id, 90)

    response = sell(client, product, '1.50')      # inside 90%, below the 2.00 cost

    assert 'cannot be sold below cost' in response.get_data(as_text=True)
    assert SaleItem.query.count() == 0


def test_selling_exactly_at_cost_is_allowed(shop):
    client, business_id, product = shop
    allow_discount(business_id, 90)
    sell(client, product, '2.00')
    assert charged() == Decimal('2.00')


def test_above_list_is_allowed(shop):
    client, _business_id, product = shop
    sell(client, product, '4.00')
    assert charged() == Decimal('4.00')


def test_deviations_are_audited(shop):
    client, business_id, product = shop
    allow_discount(business_id, 20)

    sell(client, product, '2.70')          # discount
    sell(client, product, '4.00')          # above list

    entries = AuditLog.query.filter_by(action='sale.price_override').all()
    kinds = {json.loads(e.details_json)['kind'] for e in entries}
    assert kinds == {'discount', 'above_list'}
    assert all(e.user_id is not None for e in entries)
    assert all(e.business_id == business_id for e in entries)

    discount = next(json.loads(e.details_json) for e in entries
                    if json.loads(e.details_json)['kind'] == 'discount')
    assert discount['list_price'] == '3.00'
    assert discount['charged'] == '2.70'
    assert discount['discount_percent'] == '10.00'


def test_selling_at_list_price_creates_no_audit_noise(shop):
    client, _business_id, product = shop
    sell(client, product, '3.00')
    assert AuditLog.query.filter_by(action='sale.price_override').count() == 0


def test_discount_ceiling_cannot_exceed_100(shop):
    """Above 100 the computed floor goes negative, disabling the limit entirely."""
    from sqlalchemy.exc import IntegrityError

    _client, business_id, _product = shop
    Business.query.get(business_id).max_discount_percent = Decimal('150')
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
