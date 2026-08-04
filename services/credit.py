"""Balances, statements and ageing.

Balances are computed from sales minus payments every time they are asked for,
never stored. A stored balance is a cache, and a cache that nobody reconciles
drifts - which is exactly what went wrong with stock before services/stock.py
took ownership of it (F-12). Here the sums are small and indexed, so deriving
them is cheap and always right.
"""
import datetime
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from credit.models import PAYMENT_METHODS, Payment, sale_total, settlement_of
from extensions import db
from sales.models import Sale, SaleItem

METHOD_LABELS = dict(PAYMENT_METHODS)

# Ageing buckets, in days overdue. The labels are what a wholesaler chasing debts
# actually thinks in.
AGEING_BUCKETS = [
    (0, 30, 'Current'),
    (31, 60, '31-60 days'),
    (61, 90, '61-90 days'),
    (91, None, 'Over 90 days'),
]


def _sale_totals_subquery(business_id):
    """Per-sale value, as a subquery so balances are one query rather than N."""
    return (
        db.session.query(
            SaleItem.sale_id.label('sale_id'),
            func.coalesce(func.sum(SaleItem.price_at_sale * SaleItem.quantity), 0).label('total'),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.business_id == business_id)
        .group_by(SaleItem.sale_id)
        .subquery()
    )


def _sale_payments_subquery(business_id):
    return (
        db.session.query(
            Payment.sale_id.label('sale_id'),
            func.coalesce(func.sum(Payment.amount), 0).label('paid'),
        )
        .filter(Payment.business_id == business_id)
        .group_by(Payment.sale_id)
        .subquery()
    )


def outstanding_sales(business_id, customer_id=None, as_of=None):
    """Sales with money still owed, oldest first.

    Returns [(Sale, total, paid, balance)]. Walk-in sales with no customer are
    included: the money is still owed, even if there is nobody to chase.
    """
    as_of = as_of or datetime.date.today()
    totals = _sale_totals_subquery(business_id)
    payments = _sale_payments_subquery(business_id)

    query = (
        db.session.query(
            Sale,
            totals.c.total,
            func.coalesce(payments.c.paid, 0).label('paid'),
        )
        .join(totals, totals.c.sale_id == Sale.id)
        .outerjoin(payments, payments.c.sale_id == Sale.id)
        .filter(
            Sale.business_id == business_id,
            Sale.sale_date <= as_of,
            totals.c.total > func.coalesce(payments.c.paid, 0),
        )
    )
    if customer_id is not None:
        query = query.filter(Sale.customer_id == customer_id)

    rows = query.order_by(Sale.sale_date.asc(), Sale.id.asc()).all()
    return [
        (sale, Decimal(total), Decimal(paid), Decimal(total) - Decimal(paid))
        for sale, total, paid in rows
    ]


def customer_balance(business_id, customer_id):
    """Total outstanding for one customer."""
    return sum((row[3] for row in outstanding_sales(business_id, customer_id)), Decimal('0'))


def total_outstanding(business_id):
    return sum((row[3] for row in outstanding_sales(business_id)), Decimal('0'))


def bucket_for(days_overdue):
    for low, high, label in AGEING_BUCKETS:
        if days_overdue >= low and (high is None or days_overdue <= high):
            return label
    return AGEING_BUCKETS[-1][2]


def ageing(business_id, as_of=None):
    """Outstanding money per customer, split by how long it has been owed.

    Returns [{customer, total, buckets: {label: amount}, oldest_days}], biggest
    debt first - which is the order a wholesaler wants to make calls in.
    """
    as_of = as_of or datetime.date.today()
    per_customer = {}

    for sale, _total, _paid, balance in outstanding_sales(business_id, as_of=as_of):
        days = (as_of - sale.sale_date).days
        key = sale.customer_id                       # None groups walk-in sales
        entry = per_customer.setdefault(key, {
            'customer': sale.customer,
            'total': Decimal('0'),
            'buckets': {label: Decimal('0') for _l, _h, label in AGEING_BUCKETS},
            'oldest_days': 0,
        })
        entry['total'] += balance
        entry['buckets'][bucket_for(days)] += balance
        entry['oldest_days'] = max(entry['oldest_days'], days)

    return sorted(per_customer.values(), key=lambda e: e['total'], reverse=True)


def walk_in_sales(business_id, as_of=None):
    """Outstanding sales with no registered customer, oldest first.

    The ageing report groups by customer, which collapses every walk-in into one
    anonymous row with nothing to click. The money is still owed and still has to
    be collectable, so for walk-ins the unit is the sale rather than the person.

    Returns [(Sale, total, paid, balance)].
    """
    return [row for row in outstanding_sales(business_id, as_of=as_of)
            if row[0].customer_id is None]


def bucket_totals(rows):
    """Column totals for the ageing table."""
    totals = {label: Decimal('0') for _l, _h, label in AGEING_BUCKETS}
    for row in rows:
        for label, amount in row['buckets'].items():
            totals[label] += amount
    return totals


def statement(business_id, customer_id, as_of=None):
    """Every sale and payment for one customer, oldest first.

    Returns [{date, kind, description, charged, paid, balance, ...}] with a
    running balance - the shape a customer expects to see when they query what
    they owe.

    A sale row also carries its own settlement (`settled`, `outstanding`,
    `status`) and a payment row names the sale it cleared. Without that, paying
    a sale in full leaves its row looking untouched: `paid` on a sale row is
    always zero because the money arrives as a separate row, sorted by its own
    date and possibly far down the page. Users read that as the payment having
    not registered.
    """
    as_of = as_of or datetime.date.today()

    sales = (
        Sale.query
        .options(selectinload(Sale.items))
        .filter(
            Sale.business_id == business_id,
            Sale.customer_id == customer_id,
            Sale.sale_date <= as_of,
        ).all()
    )
    payments = (
        Payment.query.filter(
            Payment.business_id == business_id,
            Payment.customer_id == customer_id,
            Payment.paid_on <= as_of,
        ).all()
    )

    # Summed from the same as-of window rather than from sale.payments, so a
    # statement run for an earlier date does not credit a sale with money that
    # had not arrived yet.
    settled = defaultdict(Decimal)
    for payment in payments:
        settled[payment.sale_id] += payment.amount

    events = []
    for s in sales:
        total = sale_total(s)
        # An overpayment reads as settled, never as negative outstanding.
        paid = min(settled[s.id], total)
        events.append({
            'date': s.sale_date, 'kind': 'sale', 'description': f'Sale #{s.id}',
            'charged': total, 'paid': Decimal('0'), 'ref': None,
            'sale_id': s.id, 'settled': paid, 'outstanding': total - paid,
            'status': settlement_of(total, settled[s.id]),
        })
    for p in payments:
        events.append({
            'date': p.paid_on, 'kind': 'payment',
            'description': METHOD_LABELS.get(p.method, p.method),
            'charged': Decimal('0'), 'paid': p.amount, 'ref': p.reference,
            'sale_id': p.sale_id, 'settled': None, 'outstanding': None,
            'status': None,
        })

    # A payment recorded the same day as a sale settles that sale, so sales sort
    # first within a date.
    events.sort(key=lambda e: (e['date'], 0 if e['kind'] == 'sale' else 1))

    running = Decimal('0')
    for event in events:
        running += event['charged'] - event['paid']
        event['balance'] = running
    return events
