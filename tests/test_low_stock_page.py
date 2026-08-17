"""The restocking list, and the two links that pointed at the wrong thing.

Reported from the running app: the dashboard's "Low Stock Items" card was named
after the number on it rather than the report it opened, and its View All button
went to the entire product catalogue, unfiltered.

The page itself is derived, like the alerts: a product leaves it the moment its
stock goes back above the reorder level, because handling the problem *is*
receiving the stock. There is nothing to dismiss and nothing to keep in step.
"""
import re

import pytest

from extensions import db
from services import notifications


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    return client, business_id


def set_levels(product, in_stock, reorder_at):
    product.quantity_in_stock = in_stock
    product.min_stock_alert = reorder_at
    db.session.commit()


# --- what appears -------------------------------------------------------------

def test_a_product_below_its_reorder_level_appears(shop, make_product):
    client, business_id = shop
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml')
    set_levels(product, in_stock=3, reorder_at=10)

    body = client.get('/products/low-stock').get_data(as_text=True)

    assert 'BelAqua 750ml' in body


def test_a_product_at_zero_appears_and_is_marked(shop, make_product):
    """Included deliberately. The alerts page keeps low and empty apart by
    severity, but this page answers "what do I buy", and zero is the most urgent
    answer to that question."""
    client, business_id = shop
    product = make_product(business_id, sku='CB-330', name='Club Beer')
    set_levels(product, in_stock=0, reorder_at=10)

    body = client.get('/products/low-stock').get_data(as_text=True)

    assert 'Club Beer' in body
    assert 'Out of stock' in body


def test_a_healthy_product_does_not_appear(shop, make_product):
    client, business_id = shop
    healthy = make_product(business_id, sku='OK-1', name='Plenty Left')
    set_levels(healthy, in_stock=500, reorder_at=10)

    body = client.get('/products/low-stock').get_data(as_text=True)

    assert 'Plenty Left' not in body
    assert 'Nothing needs restocking' in body


def test_restocking_removes_it_without_anyone_dismissing_anything(shop, make_product):
    """The property that makes this page trustworthy. Nothing is stored, so it
    cannot go on claiming a product needs ordering after it has arrived."""
    client, business_id = shop
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml')
    set_levels(product, in_stock=3, reorder_at=10)
    assert 'BelAqua 750ml' in client.get('/products/low-stock').get_data(as_text=True)

    set_levels(product, in_stock=200, reorder_at=10)

    body = client.get('/products/low-stock').get_data(as_text=True)
    assert 'BelAqua 750ml' not in body
    assert 'Nothing needs restocking' in body


def test_a_retired_product_is_not_listed(shop, make_product):
    """Deactivating a product is how you stop stocking it. Asking someone to
    reorder it would be the opposite of what they said."""
    client, business_id = shop
    product = make_product(business_id, sku='OLD-1', name='Discontinued Malt')
    set_levels(product, in_stock=0, reorder_at=10)
    product.is_active = False
    db.session.commit()

    body = client.get('/products/low-stock').get_data(as_text=True)
    assert 'Discontinued Malt' not in body


def test_the_worst_is_listed_first(shop, make_product):
    client, business_id = shop
    mild = make_product(business_id, sku='M-1', name='Mildly Low')
    empty = make_product(business_id, sku='E-1', name='Completely Empty')
    set_levels(mild, in_stock=8, reorder_at=10)
    set_levels(empty, in_stock=0, reorder_at=10)

    body = client.get('/products/low-stock').get_data(as_text=True)

    assert body.index('Completely Empty') < body.index('Mildly Low')


def test_the_page_stays_inside_the_business(shop, register, make_product):
    client, _business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='o@kd.example.com')
    theirs = make_product(other_id, sku='KD-1', name='Kumasi Special')
    set_levels(theirs, in_stock=0, reorder_at=10)

    body = client.get('/products/low-stock').get_data(as_text=True)
    assert 'Kumasi Special' not in body


def test_it_needs_permission_to_view_products(shop, make_staff):
    _client, business_id = shop
    outsider = make_staff(business_id, 'Sales Staff', 'nope@ab.example.com',
                          permissions=['sales.view'])

    assert outsider.get('/products/low-stock').status_code == 403


# --- the links that were wrong ------------------------------------------------

def test_the_dashboard_card_is_named_after_the_page_it_opens(shop):
    """It read "Low Stock Items" while opening the stock level report -
    named for the number on it rather than for where it goes.

    The card is "Restock" now and it opens the restocking list, so the rule
    holds under a different name. Asserted as the rule rather than as the
    old wording: the previous version checked for the literal string
    "Stock Level Report", which made a correct rename look like a
    regression.
    """
    client, _business_id = shop
    body = client.get('/').get_data(as_text=True)

    card = re.search(
        r'<a class="stat-cell" href="([^"]+)">\s*<span class="stat-label">'
        r'([^<]+)</span>', body)
    assert card, 'no stat cell on the dashboard at all'

    # Every cell must point somewhere, and the Restock one at the list of
    # what to reorder.
    cells = dict(re.findall(
        r'<a class="stat-cell" href="([^"]+)">\s*<span class="stat-label">([^<]+)',
        body))
    assert '/products/low-stock' in cells, 'nothing opens the restocking list'
    assert cells['/products/low-stock'].strip() == 'Restock'
    assert 'Low Stock Items' not in body


def test_view_all_goes_to_the_restocking_list(shop, make_product):
    """It pointed at the whole catalogue, unfiltered - so View All beside a low
    stock heading showed you every product you own."""
    client, business_id = shop
    product = make_product(business_id, sku='BA-750')
    set_levels(product, in_stock=3, reorder_at=10)

    body = client.get('/').get_data(as_text=True)

    assert '/products/low-stock' in body


def test_both_stock_alerts_lead_to_the_same_page(shop, make_product):
    """Low and empty stay separate alerts, because the severities differ. They
    lead to one destination, because "what do I buy" has one answer."""
    _client, business_id = shop
    low = make_product(business_id, sku='L-1', name='Low One')
    empty = make_product(business_id, sku='E-1', name='Empty One')
    set_levels(low, in_stock=3, reorder_at=10)
    set_levels(empty, in_stock=0, reorder_at=10)

    alerts = {a['kind']: a for a in notifications.for_business(business_id)}

    assert alerts['low_stock']['endpoint'] == 'products.low_stock'
    assert alerts['out_of_stock']['endpoint'] == 'products.low_stock'
