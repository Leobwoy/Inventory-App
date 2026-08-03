"""Multi-supplier price comparison — Stage 2.3.

Every unit cost the business has paid is already on PurchaseOrderItem and
nothing ever read it back, so "who is actually cheapest for this" had no answer
and the reorder went to whoever was called last time.

Pure read over order history: no new tables, and useful from the first month.
"""
import datetime
from decimal import Decimal

import pytest

from billing.models import Plan, Subscription
from extensions import db
from products.models import Supplier
from purchases.models import PurchaseOrder, PurchaseOrderItem
from services import sourcing

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml')
    suppliers = {}
    for name in ('Voltic Ghana', 'Accra Bulk', 'Takoradi Depot'):
        supplier = Supplier(business_id=business_id, name=name, phone='024')
        db.session.add(supplier)
        suppliers[name] = supplier
    db.session.commit()
    return client, business_id, product, suppliers


def order(business_id, supplier, product, cost, days_ago=0, status='received', quantity=100):
    """Record a purchase order line directly - this is history, not a UI flow."""
    po = PurchaseOrder(
        business_id=business_id,
        supplier_id=supplier.id if supplier else None,
        status=status,
        order_date=TODAY - datetime.timedelta(days=days_ago),
    )
    db.session.add(po)
    db.session.flush()
    db.session.add(PurchaseOrderItem(
        po_id=po.id, product_id=product.id, quantity_ordered=quantity,
        quantity_received=quantity, unit_cost=Decimal(cost),
    ))
    db.session.commit()
    return po


# --------------------------------------------------------------- the comparison

def test_suppliers_are_listed_cheapest_first(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '1.80')
    order(business_id, suppliers['Accra Bulk'], product, '1.65')
    order(business_id, suppliers['Takoradi Depot'], product, '1.95')

    options = sourcing.suppliers_for(business_id, product.id)

    assert [o['supplier'].name for o in options] == [
        'Accra Bulk', 'Voltic Ghana', 'Takoradi Depot']
    assert options[0]['latest'] == Decimal('1.65')


def test_latest_price_wins_over_older_ones(shop):
    """A buyer decides on what a supplier charges now, not what they once did."""
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '1.50', days_ago=60)
    order(business_id, suppliers['Voltic Ghana'], product, '2.10', days_ago=2)

    option = sourcing.suppliers_for(business_id, product.id)[0]

    assert option['latest'] == Decimal('2.10')
    assert option['best'] == Decimal('1.50')       # the number to quote back at them
    assert option['times'] == 2
    assert option['average'] == Decimal('1.80')


def test_a_supplier_creeping_up_is_visible(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '1.50', days_ago=30)
    order(business_id, suppliers['Voltic Ghana'], product, '1.90', days_ago=1)

    option = sourcing.suppliers_for(business_id, product.id)[0]
    assert option['trend'] == 'up'
    assert option['previous'] == Decimal('1.50')


def test_a_supplier_coming_down_is_visible(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '2.00', days_ago=30)
    order(business_id, suppliers['Voltic Ghana'], product, '1.70', days_ago=1)

    assert sourcing.suppliers_for(business_id, product.id)[0]['trend'] == 'down'


def test_a_single_order_has_no_trend(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '1.80')

    option = sourcing.suppliers_for(business_id, product.id)[0]
    assert option['trend'] == 'flat'
    assert option['previous'] is None


# ------------------------------------------------------------- what is excluded

@pytest.mark.parametrize('status', ['draft', 'cancelled'])
def test_uncommitted_orders_are_ignored(shop, status):
    """A draft or cancelled order is a price nobody agreed to pay."""
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '1.80', status='received')
    order(business_id, suppliers['Accra Bulk'], product, '0.05', status=status)

    options = sourcing.suppliers_for(business_id, product.id)
    assert [o['supplier'].name for o in options] == ['Voltic Ghana']


def test_orders_without_a_supplier_are_ignored(shop):
    """There is nobody to compare against."""
    client, business_id, product, suppliers = shop
    order(business_id, None, product, '1.20')
    order(business_id, suppliers['Voltic Ghana'], product, '1.80')

    assert len(sourcing.suppliers_for(business_id, product.id)) == 1


def test_zero_cost_lines_are_ignored(shop):
    """A free sample is not a price."""
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '0')
    order(business_id, suppliers['Accra Bulk'], product, '1.80')

    options = sourcing.suppliers_for(business_id, product.id)
    assert [o['supplier'].name for o in options] == ['Accra Bulk']


def test_another_tenants_prices_are_invisible(register, make_product, app):
    """Competitors' costs are the last thing that may leak."""
    _client_a, business_a = register(name='Alpha', email='a@x.example.com')
    _client_b, business_b = register(name='Beta', email='b@x.example.com')

    product_a = make_product(business_a, sku='SHARED')
    product_b = make_product(business_b, sku='SHARED')
    supplier_b = Supplier(business_id=business_b, name='Beta Supplier')
    db.session.add(supplier_b)
    db.session.commit()
    order(business_b, supplier_b, product_b, '0.10')

    assert sourcing.suppliers_for(business_a, product_a.id) == []


# ------------------------------------------------------------------- savings

def test_savings_compares_the_cheapest_against_who_you_last_used(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Accra Bulk'], product, '1.60', days_ago=40)
    order(business_id, suppliers['Voltic Ghana'], product, '2.00', days_ago=1)   # most recent

    savings = sourcing.savings_against_latest(sourcing.suppliers_for(business_id, product.id))

    assert savings['from']['supplier'].name == 'Voltic Ghana'
    assert savings['to']['supplier'].name == 'Accra Bulk'
    assert savings['per_unit'] == Decimal('0.40')


def test_no_savings_when_you_already_use_the_cheapest(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '2.00', days_ago=40)
    order(business_id, suppliers['Accra Bulk'], product, '1.60', days_ago=1)     # cheapest and latest

    assert sourcing.savings_against_latest(sourcing.suppliers_for(business_id, product.id)) is None


def test_no_savings_with_only_one_supplier(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '2.00')

    assert sourcing.savings_against_latest(sourcing.suppliers_for(business_id, product.id)) is None


# ---------------------------------------------------------------- the overview

def test_only_products_with_a_real_choice_appear(shop, make_product):
    client, business_id, product, suppliers = shop
    single = make_product(business_id, sku='ONE-SUPPLIER', name='Single sourced')

    order(business_id, suppliers['Voltic Ghana'], product, '1.80')
    order(business_id, suppliers['Accra Bulk'], product, '1.60')
    order(business_id, suppliers['Voltic Ghana'], single, '3.00')

    rows = sourcing.products_with_alternatives(business_id)
    assert [r['product'].sku for r in rows] == ['BA-750']


def test_biggest_price_gap_comes_first(shop, make_product):
    """A product where everyone charges the same is not a decision."""
    client, business_id, product, suppliers = shop
    narrow = make_product(business_id, sku='NARROW', name='Narrow spread')

    order(business_id, suppliers['Voltic Ghana'], product, '1.00')
    order(business_id, suppliers['Accra Bulk'], product, '3.00')      # spread 2.00
    order(business_id, suppliers['Voltic Ghana'], narrow, '5.00')
    order(business_id, suppliers['Accra Bulk'], narrow, '5.10')       # spread 0.10

    rows = sourcing.products_with_alternatives(business_id)
    assert [r['product'].sku for r in rows] == ['BA-750', 'NARROW']
    assert rows[0]['spread'] == Decimal('2.00')


def test_best_price_returns_the_cheapest_option(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '1.80')
    order(business_id, suppliers['Accra Bulk'], product, '1.55')

    best = sourcing.best_price(business_id, product.id)
    assert best['supplier'].name == 'Accra Bulk'
    assert best['latest'] == Decimal('1.55')


def test_best_price_is_none_for_a_product_never_bought(shop, make_product):
    client, business_id, _product, _suppliers = shop
    fresh = make_product(business_id, sku='NEVER-BOUGHT')
    assert sourcing.best_price(business_id, fresh.id) is None


# --------------------------------------------------------------------- the pages

def test_the_pages_render_with_history(shop):
    client, business_id, product, suppliers = shop
    order(business_id, suppliers['Voltic Ghana'], product, '2.00', days_ago=30)
    order(business_id, suppliers['Accra Bulk'], product, '1.60', days_ago=1)

    body = client.get('/purchases/compare').get_data(as_text=True)
    assert 'BelAqua 750ml' in body
    assert 'Accra Bulk' in body

    body = client.get(f'/purchases/compare/{product.id}').get_data(as_text=True)
    assert 'Cheapest' in body
    assert '1.60' in body


def test_the_overview_says_so_when_there_is_nothing_to_compare(shop):
    client, _business_id, _product, _suppliers = shop
    assert 'Nothing to compare yet' in client.get('/purchases/compare').get_data(as_text=True)


def test_comparison_is_a_paid_feature(shop):
    client, business_id, product, _suppliers = shop
    assert client.get('/purchases/compare').status_code == 200      # trial includes it

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='standard').one().id   # Depot
    subscription.status = 'active'
    db.session.commit()

    response = client.get('/purchases/compare', follow_redirects=True)
    assert 'not included in your current plan' in response.get_data(as_text=True)


def test_a_product_from_another_tenant_is_not_reachable(shop, register, make_product, app):
    client, _business_a, _product, _suppliers = shop
    _other, business_b = register(name='Beta', email='b@x.example.com')
    foreign = make_product(business_b, sku='BETA-1')

    assert client.get(f'/purchases/compare/{foreign.id}').status_code == 404
