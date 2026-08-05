"""What each supplier has charged for a product, over time.

Every unit cost the business has ever paid is already recorded on
PurchaseOrderItem. Nothing has ever read it back, so the question a wholesaler
asks before every reorder - who is actually cheapest for this - has had no
answer, and the reorder goes to whoever was called last time.

No new tables. This is entirely a read over purchase order history, which is why
it can show useful figures from the first month rather than needing data to
accumulate the way supplier scorecards do.

Costs are per base unit throughout, because that is how PurchaseOrderItem stores
them (services/uom.py). A carton price is derived for display, never compared -
comparing carton prices across suppliers who pack differently is exactly the
mistake this feature exists to prevent.
"""
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from products.models import Product, Supplier
from purchases.models import PurchaseOrder, PurchaseOrderItem

# Statuses that represent a real commitment. A draft or cancelled order is a
# price nobody actually agreed to pay.
REAL_ORDER_STATUSES = ('ordered', 'partially_received', 'received')


def _priced_lines(business_id, product_id=None):
    """Purchase order lines that carry a usable price, newest first."""
    query = (
        PurchaseOrderItem.query
        .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .options(joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.supplier))
        .filter(
            PurchaseOrder.business_id == business_id,
            PurchaseOrder.status.in_(REAL_ORDER_STATUSES),
            PurchaseOrder.supplier_id.isnot(None),
            # Every figure here is time-ordered - latest price, trend, who was
            # used most recently. An order with no date cannot be placed in
            # time, so it cannot answer any of them. nullslast() alone was not
            # enough: a supplier whose orders are *all* undated still produced
            # last_ordered=None, and comparing that against a real date in
            # savings_against_latest() raises TypeError.
            PurchaseOrder.order_date.isnot(None),
            PurchaseOrderItem.unit_cost.isnot(None),
            PurchaseOrderItem.unit_cost > 0,
        )
    )
    if product_id is not None:
        query = query.filter(PurchaseOrderItem.product_id == product_id)
    # nullslast: on PostgreSQL a DESC sort puts NULLs first, which would make a
    # dateless order the 'latest' price and set last_ordered to None.
    return query.order_by(PurchaseOrder.order_date.desc().nullslast(),
                          PurchaseOrderItem.id.desc()).all()


def _reduce_to_options(lines):
    """Group priced lines by supplier into the shape the comparison renders.

    Shared by suppliers_for() and the batched path so one product and a whole
    page cannot drift into answering the question differently.
    """
    by_supplier = {}
    for line in lines:
        supplier = line.purchase_order.supplier
        entry = by_supplier.setdefault(supplier.id, {
            'supplier': supplier,
            'costs': [],            # newest first
            'dates': [],
        })
        entry['costs'].append(Decimal(line.unit_cost))
        entry['dates'].append(line.purchase_order.order_date)

    results = []
    for entry in by_supplier.values():
        costs = entry['costs']
        latest = costs[0]
        previous = costs[1] if len(costs) > 1 else None
        results.append({
            'supplier': entry['supplier'],
            'latest': latest,
            'best': min(costs),
            'average': (sum(costs) / len(costs)).quantize(Decimal('0.01')),
            'times': len(costs),
            'last_ordered': entry['dates'][0],
            'previous': previous,
            'trend': _trend(latest, previous),
        })

    # Cheapest current price first - the order a buyer wants to read.
    return sorted(results, key=lambda r: r['latest'])


def _options_for_many(business_id, product_ids):
    """suppliers_for() for a set of products, in one pass over one query."""
    if not product_ids:
        return {}

    lines_by_product = {}
    for line in _priced_lines(business_id):
        if line.product_id in set(product_ids):
            lines_by_product.setdefault(line.product_id, []).append(line)
    return {product_id: _reduce_to_options(lines)
            for product_id, lines in lines_by_product.items()}


def suppliers_for(business_id, product_id):
    """Every supplier who has supplied this product, cheapest latest price first.

    Returns [{supplier, latest, best, average, times, last_ordered, trend}].

    `latest` is what they charged most recently and is what a buyer decides on;
    `best` is the lowest they have ever gone, which is the number to quote back
    at them. `trend` compares the latest against the one before it, so a supplier
    who has quietly crept up is visible.
    """
    return _reduce_to_options(_priced_lines(business_id, product_id))


def _trend(latest, previous):
    """'up', 'down' or 'flat' against the previous order from that supplier."""
    if previous is None or latest == previous:
        return 'flat'
    return 'up' if latest > previous else 'down'


def best_price(business_id, product_id):
    """The cheapest current price and who offers it, or None if never bought."""
    options = suppliers_for(business_id, product_id)
    return options[0] if options else None


def savings_against_latest(options):
    """What switching to the cheapest would save per unit, versus the most
    recently used supplier.

    None when there is nothing to compare - one supplier, or the most recent
    order was already the cheapest.
    """
    if len(options) < 2:
        return None
    dated = [option for option in options if option['last_ordered'] is not None]
    if not dated:
        return None
    most_recent = max(dated, key=lambda r: r['last_ordered'])
    cheapest = options[0]
    if cheapest['supplier'].id == most_recent['supplier'].id:
        return None
    return {
        'from': most_recent,
        'to': cheapest,
        'per_unit': most_recent['latest'] - cheapest['latest'],
    }


def products_with_alternatives(business_id, limit=None):
    """Products bought from more than one supplier, biggest spread first.

    The spread is what makes a product worth looking at: a product where every
    supplier charges the same is not a decision.
    """
    counts = (
        db.session.query(
            PurchaseOrderItem.product_id,
            func.count(func.distinct(PurchaseOrder.supplier_id)).label('supplier_count'),
        )
        .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .filter(
            PurchaseOrder.business_id == business_id,
            PurchaseOrder.status.in_(REAL_ORDER_STATUSES),
            PurchaseOrder.supplier_id.isnot(None),
            PurchaseOrderItem.unit_cost > 0,
        )
        .group_by(PurchaseOrderItem.product_id)
        .having(func.count(func.distinct(PurchaseOrder.supplier_id)) > 1)
        .all()
    )

    # Two queries for the whole page, not two per product. This ran
    # session.get(Product) and then suppliers_for() - itself a round trip - for
    # every candidate, and the route calls it with no limit for the whole
    # business, so the cost grew with the catalogue. The limit did not help
    # either: it was applied after every product had already been loaded.
    candidate_ids = [product_id for product_id, _count in counts]
    products = {
        product.id: product
        for product in Product.query.filter(
            Product.id.in_(candidate_ids), Product.business_id == business_id).all()
    } if candidate_ids else {}
    options_by_product = _options_for_many(business_id, candidate_ids)

    rows = []
    for product_id, supplier_count in counts:
        product = products.get(product_id)
        if product is None:
            continue
        options = options_by_product.get(product_id, [])
        if len(options) < 2:
            continue
        spread = options[-1]['latest'] - options[0]['latest']
        rows.append({
            'product': product,
            'options': options,
            'supplier_count': supplier_count,
            'cheapest': options[0],
            'dearest': options[-1],
            'spread': spread,
            'savings': savings_against_latest(options),
        })

    rows.sort(key=lambda r: r['spread'], reverse=True)
    return rows[:limit] if limit else rows
