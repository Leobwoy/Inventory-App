"""Query efficiency and money precision — F-15, F-26.

The N+1 assertions count real SQL rather than inspecting the query object, so
they fail if someone later removes an eager load. Counts are given generous
headroom: the point is that they stay flat as rows are added, not that they hit
an exact number.
"""
import datetime
import re
from decimal import Decimal

import pytest
from sqlalchemy import event

from extensions import db
from sales.models import Sale

TODAY = datetime.date.today()


class QueryCounter:
    """Count SELECTs issued while the block runs."""

    def __init__(self):
        self.statements = []

    def __enter__(self):
        self.statements = []

        @event.listens_for(db.engine, 'before_cursor_execute')
        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith('SELECT'):
                self.statements.append(statement)

        self._listener = record
        return self

    def __exit__(self, *exc):
        event.remove(db.engine, 'before_cursor_execute', self._listener)
        return False

    @property
    def count(self):
        return len(self.statements)

    def touching(self, table):
        return [s for s in self.statements if re.search(rf'\b{table}\b', s, re.IGNORECASE)]


@pytest.fixture
def shop_with_sales(register, make_product):
    """One business, three products, and a number of multi-line sales."""
    client, business_id = register()
    products = [make_product(business_id, sku=f'SKU-{i}', name=f'Product {i}', stock=1000)
                for i in range(3)]

    def record_sales(how_many):
        for _ in range(how_many):
            data = {'sale_date': TODAY.isoformat(), 'customer_id': '0', 'customer_name': 'W'}
            for index, product in enumerate(products):
                data[f'items-{index}-product_id'] = str(product.id)
                data[f'items-{index}-quantity'] = '2'
                data[f'items-{index}-price_at_sale'] = '3.00'
            client.post('/sales/add', data=data, follow_redirects=True)

    return client, business_id, products, record_sales


def test_sales_report_query_count_stays_flat(shop_with_sales):
    """Five sales of three lines each used to cost roughly 20 extra queries."""
    client, _business_id, _products, record_sales = shop_with_sales

    record_sales(2)
    with QueryCounter() as small:
        client.get('/reports/sales')

    record_sales(6)          # four times the data
    with QueryCounter() as large:
        client.get('/reports/sales')

    assert Sale.query.count() == 8
    # Allow a little movement for the page's other queries, but nowhere near
    # proportional: without eager loading this grows by ~4 per extra sale.
    assert large.count <= small.count + 3, (
        f'{small.count} queries for 2 sales, {large.count} for 8 - still N+1'
    )


def test_sales_report_loads_products_in_one_query(shop_with_sales):
    client, _business_id, _products, record_sales = shop_with_sales
    record_sales(5)

    with QueryCounter() as counter:
        client.get('/reports/sales')

    # 15 sale lines across 5 sales; a per-line product lookup would be ~15 hits.
    product_queries = counter.touching('product')
    assert len(product_queries) <= 4, f'{len(product_queries)} queries touched product'


def test_sales_list_does_not_query_per_row(shop_with_sales):
    client, _business_id, _products, record_sales = shop_with_sales

    record_sales(2)
    with QueryCounter() as small:
        client.get('/sales/')

    record_sales(6)
    with QueryCounter() as large:
        client.get('/sales/')

    assert large.count <= small.count + 3


def test_dashboard_aggregates_in_sql(shop_with_sales):
    """The trend used to load every sale and lazy-load every line to produce
    seven numbers (F-14).

    The budget went from 12 to 22 when the dashboard gained the Needs
    attention panel. That is a deliberate decision, not a test bent to fit:
    measured, the panel costs 10 queries and money owed costs 1.

    Why this does not follow the badge's precedent. `/products/alerts/count`
    exists because the sidebar renders on fifty-odd routes, and computing
    this for all of them would put the cost on pages that never show the
    number. The dashboard is the page that *does* show it - on a phone it is
    the first thing on the screen - so fetching it after load would leave the
    most important panel blank exactly when someone opens the app to find out
    what needs doing.

    Real duplication remains: the route counts low stock for the Restock
    figure and `notifications` counts it again. Worth collapsing one day.
    """
    client, _business_id, _products, record_sales = shop_with_sales
    record_sales(10)

    with QueryCounter() as counter:
        client.get('/')

    assert counter.count <= 22, f'{counter.count} queries to draw the dashboard'


# ------------------------------------------------------------------- money

def test_totals_are_summed_as_decimal_not_float(shop_with_sales):
    """Money must not accumulate through binary floating point (F-26)."""
    client, _business_id, products, record_sales = shop_with_sales

    # 0.1 + 0.2 != 0.3 in float; three lines at 0.10 must total exactly 0.30.
    for product in products:
        product.unit_price = Decimal('0.10')
    db.session.commit()

    data = {'sale_date': TODAY.isoformat(), 'customer_id': '0', 'customer_name': 'W'}
    for index, product in enumerate(products):
        data[f'items-{index}-product_id'] = str(product.id)
        data[f'items-{index}-quantity'] = '1'
        data[f'items-{index}-price_at_sale'] = '0.10'
    client.post('/sales/add', data=data, follow_redirects=True)

    from sales.models import SaleItem
    total = sum((i.price_at_sale * i.quantity for i in SaleItem.query.all()), Decimal('0'))
    assert isinstance(total, Decimal)
    assert total == Decimal('0.30')
    assert str(total) == '0.30'


def test_stored_prices_are_decimal(shop_with_sales):
    client, _business_id, products, record_sales = shop_with_sales
    record_sales(1)

    from sales.models import SaleItem
    item = SaleItem.query.first()
    assert isinstance(item.price_at_sale, Decimal)
    assert isinstance(products[0].unit_price, Decimal)
