"""The only place stock levels change.

StockBatch.quantity_remaining is authoritative; Product.quantity_in_stock is a
cache kept in step by these functions. Before this module existed, a sale
decremented both but bulk sale deletion restored only the cache, so the two
diverged permanently after a single deletion and every later FEFO draw
compounded the gap (F-12).

Every mutation goes through here so that invariant holds in one place rather
than being re-derived at each call site. Nothing here commits - callers own the
transaction, so a failure part-way rolls the whole operation back.
"""
import datetime

from sqlalchemy import func

from extensions import db
from products.models import Product
from purchases.models import StockBatch


class InsufficientStock(Exception):
    """Raised when a deduction would take a product below zero."""

    def __init__(self, product, requested, available):
        self.product = product
        self.requested = requested
        self.available = available
        super().__init__(
            f'Not enough stock for {product.name}: {requested} requested, {available} available.'
        )


def batch_total(product_id, business_id):
    """Authoritative on-hand quantity: the sum of remaining batch quantities."""
    return db.session.query(
        func.coalesce(func.sum(StockBatch.quantity_remaining), 0)
    ).filter(
        StockBatch.product_id == product_id,
        StockBatch.business_id == business_id,
    ).scalar() or 0


def _lock_product(product):
    """Take a row lock on the product for the rest of the transaction.

    deduct_fefo locks the batch rows it draws from, but receive creates a *new*
    batch, so there is nothing existing to lock and two concurrent receipts would
    each compute the cached total from a snapshot missing the other's row. The
    last commit then wins and Product.quantity_in_stock lands too low. Locking
    the product serialises every mutation for that product while leaving other
    products free.
    """
    db.session.query(Product.id).filter(Product.id == product.id).with_for_update().one()


def _refresh_cache(product, business_id):
    """Point Product.quantity_in_stock at the batch sum."""
    product.quantity_in_stock = batch_total(product.id, business_id)
    return product.quantity_in_stock


def receive(product, quantity, business_id, received_date, batch_number=None,
            expiry_date=None, po_item_id=None):
    """Add stock as a new batch. The only way stock enters the system."""
    if quantity <= 0:
        raise ValueError('Received quantity must be greater than zero.')

    _lock_product(product)
    batch = StockBatch(
        business_id=business_id,
        product_id=product.id,
        po_item_id=po_item_id,
        batch_number=batch_number,
        quantity_received=quantity,
        quantity_remaining=quantity,
        received_date=received_date,
        expiry_date=expiry_date,
    )
    db.session.add(batch)
    db.session.flush()
    _refresh_cache(product, business_id)
    return batch


def available_batches(product_id, business_id, for_update=False):
    """Open batches in FEFO order: soonest expiry first, undated last.

    Scoped by business_id. The original query filtered on product_id alone - the
    single place in the codebase where tenant scoping was missing (F-11). Not
    exploitable then, because product ids are globally unique and already
    tenant-checked upstream, but it broke the invariant the security model rests
    on.

    Pass for_update=True to take a row lock, which every mutating caller must do
    - see deduct_fefo.
    """
    query = StockBatch.query.filter(
        StockBatch.product_id == product_id,
        StockBatch.business_id == business_id,
        StockBatch.quantity_remaining > 0,
    ).order_by(
        StockBatch.expiry_date.asc().nulls_last(),
        StockBatch.received_date.asc(),
        StockBatch.id.asc(),
    )
    if for_update:
        query = query.with_for_update()
    return query.all()


def deduct_fefo(product, quantity, business_id):
    """Draw `quantity` down across batches, soonest-expiring first.

    Returns [(batch, taken)] so a caller can record exactly which batches a sale
    consumed. Raises InsufficientStock without mutating anything if there is not
    enough on hand.

    The batch rows are locked FOR UPDATE before availability is measured, and the
    total is computed from those same locked rows rather than a separate query.
    Without the lock, two tills selling the same product under READ COMMITTED
    both see the pre-sale total, both pass the check, and both write a value
    derived from a stale read - a lost update that can drive quantity_remaining
    negative. The lock holds until the caller's transaction ends, so concurrent
    sales of one product serialise while different products still run freely.
    """
    if quantity <= 0:
        raise ValueError('Deducted quantity must be greater than zero.')

    _lock_product(product)
    batches = available_batches(product.id, business_id, for_update=True)
    available = sum(b.quantity_remaining for b in batches)
    if available < quantity:
        raise InsufficientStock(product, quantity, available)

    drawn, outstanding = [], quantity
    for batch in batches:
        if outstanding <= 0:
            break
        taken = min(batch.quantity_remaining, outstanding)
        batch.quantity_remaining -= taken
        outstanding -= taken
        drawn.append((batch, taken))

    _refresh_cache(product, business_id)
    return drawn


def restore(product, quantity, business_id):
    """Put stock back after a sale is voided.

    Refills the batches it most plausibly came from - most recently expiring
    first, i.e. the reverse of FEFO - without ever exceeding what each batch
    originally received. Anything left over becomes an adjustment batch, so
    voiding a sale can never silently lose stock.
    """
    if quantity <= 0:
        raise ValueError('Restored quantity must be greater than zero.')

    _lock_product(product)
    # Locked for the same reason as deduct_fefo: read-then-write on
    # quantity_remaining. Ordering exactly reverses available_batches, with id as
    # the final tie-break so refills land in a deterministic order.
    partial = StockBatch.query.filter(
        StockBatch.product_id == product.id,
        StockBatch.business_id == business_id,
        StockBatch.quantity_remaining < StockBatch.quantity_received,
    ).order_by(
        StockBatch.expiry_date.desc().nulls_first(),
        StockBatch.received_date.desc(),
        StockBatch.id.desc(),
    ).with_for_update().all()

    outstanding = quantity
    for batch in partial:
        if outstanding <= 0:
            break
        headroom = batch.quantity_received - batch.quantity_remaining
        put_back = min(headroom, outstanding)
        batch.quantity_remaining += put_back
        outstanding -= put_back

    if outstanding > 0:
        # No batch to return it to - the original was deleted, or stock predates
        # batch tracking. Record it rather than dropping it on the floor.
        db.session.add(StockBatch(
            business_id=business_id,
            product_id=product.id,
            batch_number='ADJ-RESTORE',
            quantity_received=outstanding,
            quantity_remaining=outstanding,
            received_date=datetime.date.today(),
        ))

    db.session.flush()
    _refresh_cache(product, business_id)


def adjust(product, new_quantity, business_id, reason='manual adjustment'):
    """Force on-hand stock to `new_quantity` (stock count correction).

    Increases create an adjustment batch; decreases draw down FEFO.
    """
    if new_quantity < 0:
        raise ValueError('Stock cannot be negative.')

    current = batch_total(product.id, business_id)
    delta = new_quantity - current
    if delta == 0:
        return 0

    if delta > 0:
        receive(product, delta, business_id, datetime.date.today(),
                batch_number=f'ADJ-{reason[:20].upper().replace(" ", "-")}')
    else:
        deduct_fefo(product, -delta, business_id)

    # A stock count correction changes the books without a sale or a delivery to
    # explain it, so it is exactly the kind of movement the log exists for.
    from services import audit
    audit.log('stock.adjust', entity_type='product', entity_id=product.id,
              business_id=business_id, sku=product.sku,
              old=current, new=new_quantity, delta=delta, reason=reason)
    return delta


def find_drift(business_id=None):
    """Products whose cached quantity disagrees with their batch sum.

    Returns [(product, cached, actual)]. Drift means something mutated stock
    outside this module.
    """
    # Keyed by (product, business) so the sum matches batch_total() in both modes.
    # Summing batches per product alone would attribute another tenant's batch to
    # this product and report drift that does not exist.
    totals_query = db.session.query(
        StockBatch.product_id,
        StockBatch.business_id,
        func.coalesce(func.sum(StockBatch.quantity_remaining), 0),
    )
    if business_id is not None:
        totals_query = totals_query.filter(StockBatch.business_id == business_id)
    totals = {
        (product_id, biz): total
        for product_id, biz, total in totals_query.group_by(
            StockBatch.product_id, StockBatch.business_id
        ).all()
    }

    query = Product.query
    if business_id is not None:
        query = query.filter_by(business_id=business_id)

    drift = []
    for product in query.all():
        actual = totals.get((product.id, product.business_id), 0)
        if product.quantity_in_stock != actual:
            drift.append((product, product.quantity_in_stock, actual))
    return drift


def reconcile(business_id=None):
    """Repair every cached quantity from its batch sum. Returns what changed."""
    drift = find_drift(business_id)
    for product, _cached, actual in drift:
        product.quantity_in_stock = actual
    return drift
