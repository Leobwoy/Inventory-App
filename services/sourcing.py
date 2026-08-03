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
            PurchaseOrderItem.unit_cost.isnot(None),
            PurchaseOrderItem.unit_cost > 0,
        )
    )
    if product_id is not None:
        query = query.filter(PurchaseOrderItem.product_id == product_id)
    return query.order_by(PurchaseOrder.order_date.desc(), PurchaseOrderItem.id.desc()).all()


def suppliers_for(business_id, product_id):
    """Every supplier who has supplied this product, cheapest latest price first.

    Returns [{supplier, latest, best, average, times, last_ordered, trend}].

    `latest` is what they charged most recently and is what a buyer decides on;
    `best` is the lowest they have ever gone, which is the number to quote back
    at them. `trend` compares the latest against the one before it, so a supplier
    who has quietly crept up is visible.
    """
    by_supplier = {}

    for line in _priced_lines(business_id, product_id):
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
    most_recent = max(options, key=lambda r: r['last_ordered'])
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

    rows = []
    for product_id, supplier_count in counts:
        product = db.session.get(Product, product_id)
        if product is None or product.business_id != business_id:
            continue
        options = suppliers_for(business_id, product_id)
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
