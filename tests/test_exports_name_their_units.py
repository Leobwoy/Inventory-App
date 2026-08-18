"""Stage W6 — reports and exports say what unit their numbers are in.

Eleven headers named none. The visible consequence: an order placed as **10
cartons** exported as **Ordered: 240**, so anyone reconciling this sheet against
a delivery note was comparing two different things.

The design constraint that shapes all of it: **a spreadsheet cell has to stay
summable.** "13 cartons + 6 bottles" reads well on a page and cannot be totalled,
sorted or filtered. So the exports name the unit once, in a column of its own,
and every figure beside it stays a number - with whole packs and the loose
remainder split apart, and the singles total kept for checking against a
physical count.

One header list feeds PDF, Excel and CSV per report, so each fix lands in three
formats at once.
"""
import csv
import datetime
import io

import pytest

from extensions import db
from services import uom

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    carton = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                          unit_price='43.75', cost_price='38.40', stock=318,
                          base_uom='bottle', purchase_uom='carton',
                          units_per_purchase_uom=24, pack_price='1050.00',
                          sell_unit='both')
    loose = make_product(business_id, sku='SWEETS-1', name='Loose Sweets',
                         unit_price='1.00', cost_price='0.60', stock=7)
    return client, business_id, carton, loose


def rows(response):
    """A CSV export as (headers, list-of-rows)."""
    text = response.get_data(as_text=True)
    parsed = list(csv.reader(io.StringIO(text)))
    return parsed[0], parsed[1:]


def row_for(body, name):
    return next(r for r in body if r and r[0] == name)


# --- the reported round trip -------------------------------------------------

def test_a_purchase_of_ten_cartons_exports_as_ten(shop, make_po):
    """It exported as 240. Somebody reconciling this against a delivery note
    reading "10 cartons" had to know to divide."""
    client, business_id, carton, _loose = shop
    make_po(business_id, carton, quantity=240, unit_cost='38.40')

    headers, body = rows(client.get('/reports/purchases?export=csv'))
    line = row_for(body, TODAY.isoformat())

    assert 'Ordered by' in headers
    assert line[headers.index('Ordered by')] == 'carton'
    assert line[headers.index('Ordered')] == '10'
    # 38.40 a bottle is 921.60 a carton, and 10 x 921.60 is the same money as
    # 240 x 38.40 - the total is untouched precisely because both scale.
    assert line[headers.index('Cost each')] == '921.6'
    assert line[headers.index('Total')] == '9216.0'


def test_a_part_carton_falls_back_to_singles_rather_than_losing_it(shop, make_po):
    """A row that does not divide exactly reports singles for every column. The
    alternative is showing whole cartons and dropping the remainder, and a
    report that quietly loses stock is worse than one using a clumsier unit."""
    client, business_id, carton, _loose = shop
    make_po(business_id, carton, quantity=250, unit_cost='38.40')

    headers, body = rows(client.get('/reports/purchases?export=csv'))
    line = row_for(body, TODAY.isoformat())

    assert line[headers.index('Ordered by')] == 'bottle'
    assert line[headers.index('Ordered')] == '250'
    assert line[headers.index('Cost each')] == '38.4'


# --- stock, split so it stays summable ---------------------------------------

def test_the_stock_export_splits_whole_packs_from_loose(shop):
    client, _business_id, _carton, _loose = shop

    headers, body = rows(client.get('/reports/stock?export=csv'))
    line = row_for(body, 'Club Beer 330ml')

    assert line[headers.index('Sold by')] == 'carton of 24'
    assert line[headers.index('Price each')] == '1050.0'
    assert line[headers.index('In stock')] == '13'
    assert line[headers.index('Loose singles')] == '6'
    assert line[headers.index('Singles in total')] == '318'


def test_loose_goods_export_without_inventing_a_pack(shop):
    client, _business_id, _carton, _loose = shop

    headers, body = rows(client.get('/reports/stock?export=csv'))
    line = row_for(body, 'Loose Sweets')

    assert line[headers.index('Sold by')] == 'pcs'
    assert line[headers.index('In stock')] == '7'
    assert line[headers.index('Loose singles')] == '0'
    assert line[headers.index('Singles in total')] == '7'


def test_the_product_export_prices_by_the_pack(shop):
    """Same rule on the catalogue export: what the business quotes."""
    client, _business_id, carton, _loose = shop

    response = client.post('/products/bulk_action', data={
        'action': 'export_csv', 'product_ids': [str(carton.id)],
    }, follow_redirects=True)
    headers, body = rows(response)
    line = row_for(body, 'Club Beer 330ml')

    assert line[headers.index('Sold by')] == 'carton of 24'
    assert line[headers.index('Price each')] == '1050.0'
    assert line[headers.index('Cost each')] == '921.6'
    assert line[headers.index('In stock')] == '13'
    assert line[headers.index('Singles in total')] == '318'


# --- sales --------------------------------------------------------------------

def test_the_sales_export_counts_what_was_billed(shop):
    """Two cartons, not forty-eight bottles - the same guarantee the invoice
    got in W4, in the sheet the owner reconciles against it."""
    client, _business_id, carton, _loose = shop
    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0',
        'items-0-product_id': str(carton.id), 'items-0-quantity': '2',
        'items-0-sell_unit': 'purchase', 'settlement': 'paid',
    }, follow_redirects=True)

    headers, body = rows(client.get('/reports/sales?export=csv'))
    line = row_for(body, TODAY.isoformat())

    assert line[headers.index('Sold by')] == 'carton'
    assert line[headers.index('Quantity')] == '2'
    assert line[headers.index('Price each')] == '1050.0'
    assert line[headers.index('Total')] == '2100.0'


# --- the summary row still lines up ------------------------------------------

@pytest.mark.parametrize('url', ['/reports/sales?export=csv',
                                 '/reports/purchases?export=csv'])
def test_every_row_has_as_many_cells_as_there_are_headers(shop, make_po, url):
    """Both reports append a hand-built "Summary Total" row of literal blanks.
    Adding a column without adding a blank shifts the total under the wrong
    heading, which is the kind of thing nobody notices in a CSV."""
    client, business_id, carton, _loose = shop
    make_po(business_id, carton, quantity=240, unit_cost='38.40')
    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0',
        'items-0-product_id': str(carton.id), 'items-0-quantity': '2',
        'items-0-sell_unit': 'purchase', 'settlement': 'paid',
    }, follow_redirects=True)

    headers, body = rows(client.get(url))

    assert body, 'nothing was exported'
    for line in body:
        assert len(line) == len(headers)
    summary = body[-1]
    assert summary[-2] == 'Summary Total', 'the total moved out from under its label'
