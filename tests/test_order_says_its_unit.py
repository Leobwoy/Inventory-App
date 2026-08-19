"""Stage W3 — the purchase order says which unit its price is in.

The reported confusion, in the user's words:

    "Why is it that in the purchase order form, the prices for the carton is in
    units? I don't know how that works. You have to explain it to me first."

They were reading a box they fill in with a carton price, labelled "Unit Cost",
directly above a comparison quoting a per-bottle figure. Both numbers were
correct and nothing on the page said they were in different units.

**The comparison itself stays per single, deliberately.** `services/sourcing.py`
says why in its docstring and it is the reason the feature exists: two suppliers
who pack the same drink 12 and 24 to a carton cannot be compared on carton
price. What changed is only what is displayed - scaled up to the unit actually
being typed, with the per-single figure kept as a quiet second line.

Scope note. The scaling and the wording happen in the page's script, so what is
asserted here is what the server controls: the label, the data the script reads,
and the elements it writes into. The arithmetic was checked in the browser
against seeded data - a carton of 12 whose best price is 0.46 a piece reads
"Best so far: 5.52 a carton", "That is 0.46 each", and typing 7.20 gives "this
is 1.68 more a carton" - and those figures are recorded in the progress tracker
rather than restated here as a string match on JavaScript source.
"""
import datetime
import re
from decimal import Decimal

import pytest

from extensions import db
from products.models import Supplier
from purchases.models import PurchaseOrder, PurchaseOrderItem
from services import sourcing

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    """Club Beer in cartons of 24, and a loose product with no pack at all."""
    client, business_id = register()
    carton = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                          unit_price='43.75', cost_price='38.40',
                          base_uom='bottle', purchase_uom='carton',
                          units_per_purchase_uom=24, pack_price='1050.00',
                          sell_unit='both')
    loose = make_product(business_id, sku='SWEETS-1', name='Loose Sweets',
                         unit_price='1.00', cost_price='0.60')
    supplier = Supplier(business_id=business_id, name='Accra Bulk', phone='024')
    db.session.add(supplier)
    db.session.commit()
    return client, business_id, carton, loose, supplier


def hint_elements(page):
    """Which price-hint elements the page actually renders.

    A substring check reads `.price-hint-base` out of the script's own selector
    and reports it present on a plan that never rendered it. Third time this
    template family has produced that false pass, so it is a helper now.
    """
    return {name for name in ('price-hint', 'price-hint-base')
            if re.search(r'<small[^>]*class="[^"]*%s[\s"]' % name, page)}


def order(business_id, supplier, product, cost, quantity=240):
    po = PurchaseOrder(business_id=business_id, supplier_id=supplier.id,
                       status='received', order_date=TODAY)
    db.session.add(po)
    db.session.flush()
    db.session.add(PurchaseOrderItem(po_id=po.id, product_id=product.id,
                                     quantity_ordered=quantity,
                                     quantity_received=quantity,
                                     unit_cost=Decimal(cost)))
    db.session.commit()
    return po


# --- the decision this stage did NOT make ------------------------------------

def test_supplier_comparison_stays_per_single_unit(shop):
    """The load-bearing one. Inverting `sourcing` to compare carton prices would
    look consistent with the rest of Stage W and would break the feature: a
    supplier selling 12 to a carton would beat one selling 24 on every product,
    for no reason except the box being smaller.

    Kept as its own test because "make it all cartons" is exactly the tidying
    somebody will attempt later.
    """
    _client, business_id, carton, _loose, supplier = shop
    # 921.60 a carton of 24 is 38.40 a bottle - recorded per bottle, as always.
    order(business_id, supplier, carton, '38.40')

    best = sourcing.best_price(business_id, carton.id)
    assert best['latest'] == Decimal('38.40'), 'the comparison left base units'
    assert best['latest'] * 24 == Decimal('921.60')


# --- what the page has to say ------------------------------------------------

def test_the_cost_box_no_longer_claims_to_be_a_unit_cost(shop):
    """"Unit Cost" named a unit the page never identified. It says "Cost" now,
    and the script completes it with the product's own word."""
    client, _business_id, _carton, _loose, _supplier = shop

    page = client.get('/purchases/add').get_data(as_text=True)

    assert 'Unit Cost' not in page
    # The element, not the substring - the script names the same class in a
    # selector, so `'cost-unit-word' in page` passes with the span deleted.
    # Caught by falsification, having already been caught twice elsewhere.
    assert re.search(r'<span[^>]*class="[^"]*cost-unit-word[\s"]', page),         'nothing on the page can name the unit'


def test_the_page_carries_each_products_own_words(shop):
    """The script cannot invent "carton"; it reads it from here, which is the
    same data the server derives the order unit from, so the two cannot
    disagree about what a line means."""
    import json

    client, _business_id, carton, loose, _supplier = shop

    page = client.get('/purchases/add').get_data(as_text=True)
    blob = re.search(r'id="product-uom-data"[^>]*>(.*?)</script>', page, re.S)
    assert blob, 'the page lost the unit data'
    data = json.loads(blob.group(1))

    assert data[str(carton.id)] == {'per': 24, 'base': 'bottle', 'purchase': 'carton'}
    assert data[str(loose.id)]['per'] == 1, 'a product with no pack is ordered singly'


def test_the_per_single_figure_gets_its_own_line(shop):
    """Both figures on screen, the typed unit leading. One line reading
    "1,050.00 a carton (43.75 a bottle)" is how the confusion started."""
    client, _business_id, carton, _loose, supplier = shop
    order(business_id=carton.business_id, supplier=supplier, product=carton,
          cost='38.40')

    page = client.get('/purchases/add').get_data(as_text=True)

    assert hint_elements(page) == {'price-hint', 'price-hint-base'},         'the per-single figure has nowhere to go'


def test_the_second_line_is_absent_without_the_comparison_feature(shop):
    """Price comparison is a paid feature. The quiet second line is part of it,
    so a plan without it must not render an empty hanging element."""
    from billing.models import Plan, Subscription

    client, business_id, _carton, _loose, _supplier = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    # `paid_through` as well as the status, or `effective_plan` reads the
    # subscription as lapsed and falls back to Free - which has no purchase
    # orders at all, so the page under test would redirect rather than render.
    subscription.paid_through = TODAY + datetime.timedelta(days=30)
    db.session.commit()

    page = client.get('/purchases/add').get_data(as_text=True)

    assert hint_elements(page) == set(), 'a hanging element with nothing to say'
    assert re.search(r'<span[^>]*class="[^"]*cost-unit-word', page),         'naming the unit is not a paid feature'
