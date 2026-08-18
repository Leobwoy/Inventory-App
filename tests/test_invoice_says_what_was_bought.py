"""Stage W4 — the invoice says what the customer actually bought.

`SaleItem.sold_as` and `price_per_sold_unit` were added in Stage U2, and the
migration that added the columns says in as many words that "the invoice then
reads 2 cartons rather than 48 bottles". No template ever called either. A
two-carton sale printed **₵43.75 × 48** to the customer - arithmetically correct,
and not what anybody agreed to.

The line still stores 48, because 48 bottles is what left the shelf and every
stock query depends on it. Only what is printed changes, and the line total is
deliberately still `price_at_sale × quantity` so the arithmetic on the page is
the arithmetic in the database.
"""
import datetime
import re
from decimal import Decimal

import pytest

from extensions import db
from sales.models import Sale, SaleItem

TODAY = datetime.date.today()


@pytest.fixture
def carton_shop(register, make_product):
    """Club Beer: carton of 24 at 1,050, also sold singly. 480 in stock."""
    client, business_id = register()
    product = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                           unit_price='43.75', cost_price='38.40', stock=480,
                           base_uom='bottle', purchase_uom='carton',
                           units_per_purchase_uom=24, pack_price='1050.00',
                           sell_unit='both')
    return client, business_id, product


def sell(client, product, quantity, unit='base', price=None):
    data = {'sale_date': TODAY.isoformat(), 'customer_id': '0',
            'items-0-product_id': str(product.id),
            'items-0-quantity': str(quantity),
            'items-0-sell_unit': unit, 'settlement': 'paid'}
    if price is not None:
        data['items-0-price_at_sale'] = str(price)
    return client.post('/sales/add', data=data, follow_redirects=True)


def cells(page, label):
    """Every <td> carrying this data-label, tags stripped."""
    found = re.findall(r'<td[^>]*data-label="%s"[^>]*>(.*?)</td>' % label, page, re.S)
    return [' '.join(re.sub(r'<[^>]+>', ' ', c).split()) for c in found]


# --- what the customer reads -------------------------------------------------

def test_a_carton_sale_reads_as_cartons(carton_shop):
    """The headline. Two cartons at 1,050, not forty-eight bottles at 43.75."""
    client, _business_id, product = carton_shop
    sell(client, product, 2, 'purchase')
    sale = Sale.query.order_by(Sale.id.desc()).first()

    page = client.get('/sales/invoice/%d' % sale.id).get_data(as_text=True)

    assert cells(page, 'Quantity') == ['2 cartons']
    assert cells(page, 'Unit Price') == ['₵1050.00']
    assert cells(page, 'Total') == ['₵2100.00']


def test_the_line_total_still_matches_the_database_exactly(carton_shop):
    """The printed total is `price_at_sale × quantity` and nothing else. Deriving
    it from the rounded per-carton figure instead would drift from what was
    charged, which is the F-41 mistake in a new place."""
    client, _business_id, product = carton_shop
    sell(client, product, 2, 'purchase')
    line = SaleItem.query.order_by(SaleItem.id.desc()).first()

    assert line.price_at_sale * line.quantity == Decimal('2100.000000')
    assert line.quantity == 48, 'stock still moves in bottles'
    assert line.price_per_sold_unit == Decimal('1050.00')


def test_one_carton_is_singular(carton_shop):
    client, _business_id, product = carton_shop
    sell(client, product, 1, 'purchase')
    sale = Sale.query.order_by(Sale.id.desc()).first()

    page = client.get('/sales/invoice/%d' % sale.id).get_data(as_text=True)

    assert cells(page, 'Quantity') == ['1 carton']


def test_a_single_sale_still_reads_in_singles(carton_shop):
    """The other direction. Selling three bottles out of a carton is a real
    thing a wholesaler does, and it must not print "0 cartons"."""
    client, _business_id, product = carton_shop
    sell(client, product, 3, 'base')
    sale = Sale.query.order_by(Sale.id.desc()).first()

    page = client.get('/sales/invoice/%d' % sale.id).get_data(as_text=True)

    assert cells(page, 'Quantity') == ['3 bottles']
    assert cells(page, 'Total') == ['₵131.25']


def test_a_discount_is_struck_through_in_the_same_unit(carton_shop):
    """A carton sold at 1,000 against a list of 1,050 must not show 1,000.00
    struck through against 48.00 - the list price is stored per bottle."""
    from auth.models import Business

    client, business_id, product = carton_shop
    Business.query.get(business_id).max_discount_percent = Decimal('20')
    db.session.commit()

    sell(client, product, 2, 'purchase', price='1000.00')
    sale = Sale.query.order_by(Sale.id.desc()).first()

    page = client.get('/sales/invoice/%d' % sale.id).get_data(as_text=True)
    unit_cell = cells(page, 'Unit Price')[0]

    assert '1000.00' in unit_cell
    assert '1050.00' in unit_cell, 'the struck price is not in the carton unit'
    assert '48.00' not in unit_cell, 'the struck price fell back to a bottle'


# --- the same, on the page that prints many at once --------------------------

def test_bulk_invoices_say_the_same_thing(carton_shop):
    client, _business_id, product = carton_shop
    sell(client, product, 2, 'purchase')
    sale = Sale.query.order_by(Sale.id.desc()).first()

    page = client.get('/sales/bulk_print_invoices?ids=%d' % sale.id).get_data(as_text=True)

    assert cells(page, 'Quantity') == ['2 cartons']
    assert cells(page, 'Total') == ['₵2100.00']


def test_bulk_invoices_no_longer_print_six_decimals(carton_shop):
    """A separate bug on the same page: no format at all, so a carton line
    printed 41.666667 to a customer. price_at_sale is Numeric(14,6) precisely
    because it is derived from a pack price."""
    client, _business_id, product = carton_shop
    product.pack_price = Decimal('1000.00')          # 41.666... a bottle
    db.session.commit()
    sell(client, product, 2, 'purchase')
    sale = Sale.query.order_by(Sale.id.desc()).first()

    page = client.get('/sales/bulk_print_invoices?ids=%d' % sale.id).get_data(as_text=True)

    assert '41.666667' not in page
    assert '2000.000000' not in page
    assert cells(page, 'Total') == ['₵2000.00']
    assert 'Grand Total' in page and '2000.00' in page
