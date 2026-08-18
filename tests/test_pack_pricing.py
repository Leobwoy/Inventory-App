"""Selling by the carton — Stage U1, the schema and the arithmetic.

No user interface yet. This commit only makes it *possible* to say what a pack
costs; nothing sells one until U2, and every existing product behaves exactly as
it did. That split is deliberate: if a sale later charges the wrong money, it
went wrong in the sale path, never in this arithmetic.

The number that matters here is the one that cannot be derived. A carton of 24
at GHS 1,050 is GHS 43.75 a bottle against GHS 48 singly, and that gap is the
entire reason a shop buys a carton rather than 24 bottles. No arithmetic on the
single price produces it, so it is stored.
"""
from decimal import Decimal

import pytest
import sqlalchemy

from extensions import db
from products.models import Product
from services import uom


@pytest.fixture
def carton(register, make_product):
    """Club Beer: bought and sold by the carton of 24, also sold singly."""
    client, business_id = register()
    product = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                           unit_price='48.00', cost_price='38.40')
    product.base_uom = 'bottles'
    product.purchase_uom = 'carton'
    product.units_per_purchase_uom = 24
    product.pack_price = Decimal('1050.00')
    product.sell_unit = 'both'
    db.session.commit()
    return client, business_id, product


# --- the price that cannot be derived ---------------------------------------

def test_a_stored_pack_price_is_what_a_pack_costs(carton):
    _client, _business_id, product = carton

    assert uom.price_for(product, uom.PURCHASE) == Decimal('1050.00')
    assert uom.price_for(product, uom.BASE) == Decimal('48.00')


def test_the_saving_is_visible_per_piece(carton):
    """43.75 a bottle inside the carton against 48 singly. This is the figure
    the product form shows back, so a carton price typed into the singles box is
    obvious before it is saved rather than weeks later."""
    _client, _business_id, product = carton

    assert uom.per_base_price(product) == Decimal('43.75')
    assert uom.per_base_price(product) < Decimal(str(product.unit_price))


def test_without_a_pack_price_a_pack_is_simply_the_multiple(carton):
    """Null is not zero and not free. It means nobody has negotiated a case
    price, which is true of every product that existed before this column."""
    _client, _business_id, product = carton
    product.pack_price = None
    db.session.commit()

    assert uom.price_for(product, uom.PURCHASE) == Decimal('1152.00')  # 24 x 48
    assert uom.per_base_price(product) == Decimal('48.00')


def test_a_product_with_no_real_pack_has_one_price(carton):
    """Selling 'a carton of 1 piece' is two names for the same thing, so a
    pack price on such a product must not be charged for a single."""
    _client, _business_id, product = carton
    product.units_per_purchase_uom = 1
    db.session.commit()

    assert uom.price_for(product, uom.PURCHASE) == Decimal('48.00')
    assert uom.sell_units(product) == [uom.BASE]


# --- what may be sold --------------------------------------------------------

@pytest.mark.parametrize('setting,expected', [
    ('base', [uom.BASE]),
    ('purchase', [uom.PURCHASE]),
    ('both', [uom.PURCHASE, uom.BASE]),
])
def test_sell_unit_decides_the_choices(carton, setting, expected):
    _client, _business_id, product = carton
    product.sell_unit = setting
    db.session.commit()

    assert uom.sell_units(product) == expected
    assert uom.default_sell_unit(product) == expected[0]


def test_a_wholesaler_selling_only_cartons_starts_on_cartons(carton):
    """The form opens on what the business actually does, so the common case is
    no taps at all."""
    _client, _business_id, product = carton
    product.sell_unit = 'purchase'
    db.session.commit()

    assert uom.default_sell_unit(product) == uom.PURCHASE


# --- the hardening: safety moved out of the callers --------------------------

def test_a_quantity_is_not_multiplied_without_a_real_conversion(carton):
    """`to_base` multiplied on the pack count alone, so a product whose two unit
    names matched would still be multiplied if PURCHASE was passed. It was safe
    only because both call sites guarded first - and safety living in the
    callers lasts until the third caller."""
    _client, _business_id, product = carton
    product.purchase_uom = 'bottles'          # same name as base: not a conversion
    db.session.commit()

    assert uom.has_conversion(product) is False
    assert uom.to_base(product, 2, uom.PURCHASE) == 2, 'multiplied by a pack that is not one'


def test_a_cost_is_not_divided_without_a_real_conversion(carton):
    _client, _business_id, product = carton
    product.purchase_uom = 'bottles'
    db.session.commit()

    assert uom.cost_to_base(product, '48.00', uom.PURCHASE) == Decimal('48.00')


def test_a_real_conversion_still_converts(carton):
    """The guard must not have turned the feature off."""
    _client, _business_id, product = carton

    assert uom.to_base(product, 2, uom.PURCHASE) == 48
    assert uom.cost_to_base(product, '1050.00', uom.PURCHASE) == Decimal('43.750000')


# --- the schema --------------------------------------------------------------

def test_existing_products_are_untouched(register, make_product):
    """This migration adds; it does not backfill. A product made before it sells
    in pieces at its single price, which is what it already meant."""
    _client, business_id = register()
    product = make_product(business_id, unit_price='3.00')

    assert product.pack_price is None
    assert product.sell_unit == 'base'
    assert uom.price_for(product, uom.BASE) == Decimal('3.00')


def test_a_pack_of_zero_is_refused_by_the_database(carton):
    """`uom.factor()` clamps a bad count to 1 at read time, which hides a broken
    row rather than preventing it. The form asks for min=1 but with Optional(),
    and the route writes `... or 1`. The constraint is the only thing that
    actually stops the row existing."""
    _client, _business_id, product = carton

    product.units_per_purchase_uom = 0
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_an_unknown_selling_unit_is_refused_by_the_database(carton):
    _client, _business_id, product = carton

    product.sell_unit = 'crateish'
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_nothing_about_buying_changed(carton):
    """The buy side has worked for two stages. This commit must not touch it."""
    _client, _business_id, product = carton

    assert uom.factor(product) == 24
    assert uom.has_conversion(product) is True
    # W5: 'carton' is what the business typed and 'cartons' is what ten of
    # them are called. This asserted the singular, against describe's own
    # docstring example, since U1.
    assert uom.describe(product, 246) == '10 cartons + 6 bottles (246 bottles)'
    assert uom.cost_per_purchase_unit(product, '2.00') == Decimal('48.00')
