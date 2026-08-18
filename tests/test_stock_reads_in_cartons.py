"""Stage W5 — stock is read in the unit the business counts in.

Everything is stored in base units and that does not change: it is what makes
FEFO, batch expiry and `flask reconcile-stock` work. What changes is that a
wholesaler no longer has to divide by 24 in their head to know whether they are
about to run out.

The user chose the remainder over rounding: "13 cartons + 6 bottles", not "13
cartons". A carton gets broken open the first time somebody buys three bottles,
and those six loose bottles are real stock sitting on the floor.

The low-stock page is the sharpest case. Its reorder level is typed in cartons
on the product form (W2) and was read back in bottles here, so the two numbers
being compared were the same figure in different currencies.
"""
from decimal import Decimal

import pytest

from extensions import db
from services import notifications, uom


@pytest.fixture
def shop(register, make_product):
    """Club Beer by the carton of 24, and loose sweets with no pack."""
    client, business_id = register()
    carton = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                          unit_price='43.75', cost_price='38.40', stock=318,
                          base_uom='bottle', purchase_uom='carton',
                          units_per_purchase_uom=24, pack_price='1050.00',
                          sell_unit='both')
    loose = make_product(business_id, sku='SWEETS-1', name='Loose Sweets',
                         unit_price='1.00', cost_price='0.60', stock=7)
    return client, business_id, carton, loose


# --- the arithmetic ----------------------------------------------------------

def test_a_part_carton_keeps_its_remainder(shop):
    """318 bottles is thirteen cartons and six loose, not "thirteen cartons"
    and not "13.25 cartons"."""
    _client, _business_id, carton, _loose = shop

    assert uom.in_packs(carton, 318) == '13 cartons + 6 bottles'
    assert uom.describe(carton, 318) == '13 cartons + 6 bottles (318 bottles)'


def test_a_whole_number_of_cartons_says_nothing_about_a_remainder(shop):
    _client, _business_id, carton, _loose = shop

    assert uom.in_packs(carton, 240) == '10 cartons'
    assert uom.in_packs(carton, 24) == '1 carton'


def test_less_than_one_carton_reads_in_singles(shop):
    """"0 cartons + 18 bottles" is worse than "18 bottles", and this is exactly
    the case the low-stock alert is about."""
    _client, _business_id, carton, _loose = shop

    assert uom.in_packs(carton, 18) == '18 bottles'
    assert uom.in_packs(carton, 0) == '0 bottles'


def test_a_product_with_no_pack_is_untouched(shop):
    _client, _business_id, _carton, loose = shop

    assert uom.in_packs(loose, 7) == '7 pcs'
    assert uom.describe(loose, 7) == '7 pcs'


# --- the screens -------------------------------------------------------------

def test_the_product_list_counts_in_cartons(shop):
    client, _business_id, _carton, _loose = shop

    page = client.get('/products/').get_data(as_text=True)

    assert '13 cartons + 6 bottles in stock' in page
    assert '318 in stock' not in page
    assert '7 pcs in stock' in page, 'loose goods lost their count'


def test_the_low_stock_page_compares_like_with_like(shop):
    """The reorder level is typed in cartons, so reading it back in bottles put
    the two numbers being compared in different units."""
    client, _business_id, carton, _loose = shop
    carton.quantity_in_stock = 48           # 2 cartons
    carton.min_stock_alert = 120            # 5 cartons
    db.session.commit()

    page = client.get('/products/low-stock').get_data(as_text=True)

    assert '2 cartons' in page, 'stock did not read in cartons'
    assert '5 cartons' in page, 'the reorder level did not read in cartons'
    assert '3 cartons' in page, 'the shortfall did not read in cartons'


def test_the_stock_report_keeps_the_base_total(shop):
    """A stock report gets checked against a physical count, so the number of
    individual bottles is the thing being verified."""
    client, _business_id, _carton, _loose = shop

    page = client.get('/reports/stock').get_data(as_text=True)

    assert '13 cartons + 6 bottles (318 bottles)' in page


def test_goods_receipt_states_what_was_ordered_in_cartons(shop, make_po):
    """The page types its quantities in cartons - the server derives that unit
    and ignores anything posted - so the read-only figures beside the input had
    to stop being in bottles."""
    client, business_id, carton, _loose = shop
    po, _item = make_po(business_id, carton, quantity=240)

    page = client.get('/purchases/receive/%d' % po.id).get_data(as_text=True)

    assert '10 cartons ordered' in page
    assert '240 ordered' not in page


# --- the alert that appears in two places ------------------------------------

def test_the_low_stock_alert_names_a_unit(shop):
    """It read "Club Beer 330ml (18 left)" - no unit at all - on the dashboard
    and the alerts page. 18 bottles and 18 cartons are different decisions."""
    _client, business_id, carton, loose = shop
    carton.quantity_in_stock = 18
    carton.min_stock_alert = 120
    loose.min_stock_alert = 0
    db.session.commit()

    alerts = notifications.for_business(business_id)
    low = [a for a in alerts if a['kind'] == 'low_stock']

    assert low, 'the low stock alert did not fire'
    assert '(18 bottles left)' in low[0]['detail']
