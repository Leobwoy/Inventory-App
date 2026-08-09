"""What needs someone's attention right now.

Derived, never stored. Every alert here is a fact about the current state of the
business - this product is below its reorder level, this batch expires on
Friday, this customer has owed you money for ninety days - so it is computed on
read and disappears when the fact stops being true.

That is a deliberate choice against a notifications table. A stored alert can be
dismissed while the thing it warns about is still true, and then the screen says
everything is fine while the stock is still at zero. Nothing here can be marked
as read, because there is nothing to read: there is only what is the case.

The cost is that this cannot tell you about the past - "you sold out of Club
Beer last Tuesday" is not expressible. That would be an events table, and it is
a different feature.

Every alert carries a `kind`, a `severity`, a sentence a human can act on, and a
link to the page where they would act. Ordered by what deserves attention first.
"""
import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from extensions import db
from products.models import ItemGroup, Product
from purchases.models import StockBatch

#: Worst first. The dashboard and the bell both read this order.
SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}


def _alert(kind, severity, title, detail, endpoint, params=None, count=1):
    """One alert.

    Carries the endpoint and its arguments rather than a built URL, so nothing
    here needs a request context. That keeps this callable from a CLI command, a
    scheduled job, or the SMS reminders that will want the same list later - and
    it is the template's business to turn a route name into a link anyway.
    """
    return {'kind': kind, 'severity': severity, 'title': title,
            'detail': detail, 'endpoint': endpoint, 'params': params or {},
            'count': count}


def out_of_stock(business_id):
    """Products at zero. Every one of these is a sale that cannot be made."""
    return (Product.query
            .filter(Product.business_id == business_id,
                    Product.is_active.is_(True),
                    Product.quantity_in_stock <= 0)
            .order_by(Product.name)
            .all())


def low_stock(business_id):
    """At or below the reorder level, but not yet empty.

    Separate from out_of_stock on purpose: one is a warning and the other is
    already costing money, and folding them together loses that.
    """
    return (Product.query
            .filter(Product.business_id == business_id,
                    Product.is_active.is_(True),
                    Product.quantity_in_stock > 0,
                    Product.quantity_in_stock <= Product.min_stock_alert)
            .order_by(Product.quantity_in_stock.asc(), Product.name)
            .all())


def expiring_batches(business_id, within_days=None):
    """Stock nearing expiry, for the item groups that asked to be told.

    Restricted to groups with track_expiry, which is the whole point of that
    flag: a wholesaler of bottled water does not want to hear about it (D1).
    """
    from auth.models import Business

    if within_days is None:
        business = db.session.get(Business, business_id)
        within_days = (business.expiry_alert_days if business else 30) or 30

    today = datetime.date.today()
    horizon = today + datetime.timedelta(days=within_days)
    return (StockBatch.query
            .join(Product, Product.id == StockBatch.product_id)
            .join(ItemGroup, ItemGroup.id == Product.item_group_id)
            .options(joinedload(StockBatch.product))
            .filter(StockBatch.business_id == business_id,
                    StockBatch.quantity_remaining > 0,
                    StockBatch.expiry_date.isnot(None),
                    # Not yet expired. Without this the two lists overlap: an
                    # expired batch is also "within the horizon", so the same
                    # crate appears as a critical alert and a warning at once,
                    # and the badge counts it twice.
                    StockBatch.expiry_date >= today,
                    StockBatch.expiry_date <= horizon,
                    ItemGroup.track_expiry.is_(True))
            .order_by(StockBatch.expiry_date.asc())
            .all())


def expired_batches(business_id):
    """Already past their date and still counted as sellable stock.

    Worse than "expiring soon": this stock is in the FEFO queue and will be
    handed to the next customer who buys that product.
    """
    return (StockBatch.query
            .join(Product, Product.id == StockBatch.product_id)
            .join(ItemGroup, ItemGroup.id == Product.item_group_id)
            .options(joinedload(StockBatch.product))
            .filter(StockBatch.business_id == business_id,
                    StockBatch.quantity_remaining > 0,
                    StockBatch.expiry_date.isnot(None),
                    StockBatch.expiry_date < datetime.date.today(),
                    ItemGroup.track_expiry.is_(True))
            .order_by(StockBatch.expiry_date.asc())
            .all())


def overdue_credit(business_id, days=60):
    """Debt older than `days`. The list a wholesaler makes calls from."""
    from services import credit

    rows = credit.ageing(business_id)
    return [row for row in rows if row['oldest_days'] > days]


def for_business(business_id):
    """Every alert for one business, worst first.

    One list rather than a page per concern, because the question being asked is
    "what needs me today", and the answer does not sort itself by which module
    happens to produce it.
    """
    from services import limits

    alerts = []

    expired = expired_batches(business_id)
    if expired:
        units = sum(b.quantity_remaining for b in expired)
        alerts.append(_alert(
            'expired', 'critical',
            f'{len(expired)} batch{"es" if len(expired) > 1 else ""} already expired',
            f'{units} units are past their date and still counted as sellable. '
            'FEFO will hand them to the next customer.',
            'products.list_products', {'stock': 'expiring'}, len(expired)))

    empty = out_of_stock(business_id)
    if empty:
        alerts.append(_alert(
            'out_of_stock', 'critical',
            f'{len(empty)} product{"s" if len(empty) > 1 else ""} out of stock',
            'Every one of these is a sale you cannot make: '
            + ', '.join(p.name for p in empty[:3])
            + (f' and {len(empty) - 3} more' if len(empty) > 3 else ''),
            'products.list_products', {'stock': 'out'}, len(empty)))

    soon = expiring_batches(business_id)
    if soon:
        nearest = soon[0].expiry_date
        alerts.append(_alert(
            'expiring', 'warning',
            f'{len(soon)} batch{"es" if len(soon) > 1 else ""} expiring soon',
            f'The earliest goes on {nearest:%d %b}. Sell or discount these first.',
            'products.list_products', {'stock': 'expiring'}, len(soon)))

    running_out = low_stock(business_id)
    if running_out:
        alerts.append(_alert(
            'low_stock', 'warning',
            f'{len(running_out)} product{"s" if len(running_out) > 1 else ""} below reorder level',
            'Lowest: ' + ', '.join(
                f'{p.name} ({p.quantity_in_stock} left)' for p in running_out[:3]),
            'products.list_products', {'stock': 'low'}, len(running_out)))

    if limits.has_feature('credit_ledger', business_id):
        overdue = overdue_credit(business_id)
        if overdue:
            total = sum((row['total'] for row in overdue), Decimal('0'))
            alerts.append(_alert(
                'overdue_credit', 'warning',
                f'{len(overdue)} customer{"s" if len(overdue) > 1 else ""} overdue past 60 days',
                f'₵{total:,.2f} outstanding. Oldest: '
                f'{max(row["oldest_days"] for row in overdue)} days.',
                'credit.dashboard', {}, len(overdue)))

    alerts.extend(_subscription_alerts(business_id))
    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a['severity'], 9))
    return alerts


def _subscription_alerts(business_id):
    """A lapsing trial or plan, said before it lapses rather than after.

    Someone who discovers a downgrade by finding a feature gone does not come
    back. Someone warned three days out has a decision to make.
    """
    from billing.models import Subscription, days_until

    subscription = Subscription.query.filter_by(business_id=business_id).first()
    if subscription is None:
        return []

    now = datetime.datetime.utcnow()
    alerts = []

    if subscription.status == 'trialing' and subscription.trial_ends_at:
        days = days_until(subscription.trial_ends_at, now)
        if 0 < days <= 3:
            alerts.append(_alert(
                'trial_ending', 'warning',
                f'Your free trial ends in {days} day{"s" if days != 1 else ""}',
                'Pick a plan to keep purchase orders, the credit book and '
                'offline selling.',
                'billing.overview'))

    if subscription.status in ('active', 'grace') and subscription.paid_through:
        days = days_until(subscription.paid_through, now)
        if 0 < days <= 5:
            alerts.append(_alert(
                'plan_ending', 'warning',
                f'Your plan runs out in {days} day{"s" if days != 1 else ""}',
                'Mobile money cannot renew on its own, so this one needs you.',
                'billing.overview'))

    return alerts


def count_for(business_id):
    """How many alerts, for the badge. Cached per request.

    The bell renders on every page, and recomputing this per template call would
    make the count the most expensive thing on the screen.
    """
    from flask import g, has_request_context

    if not has_request_context():
        return len(for_business(business_id))

    cache = getattr(g, '_alert_cache', None)
    if cache is None:
        cache = g._alert_cache = {}
    if business_id not in cache:
        cache[business_id] = for_business(business_id)
    return len(cache[business_id])


#: Alert kinds needing more than the products.view the alerts page asks for.
#:
#: The page deliberately spans modules - the question is "what needs me today" -
#: and that walks straight through two permission gates. A stock clerk holding
#: only products.view would otherwise read the total owed by customers, and how
#: long the plan has left, off a screen they are allowed to open, having been
#: refused both of the pages that figure came from.
ALERT_PERMISSIONS = {
    'overdue_credit': 'credit.view',
    'trial_ending': 'settings.manage',
    'plan_ending': 'settings.manage',
}


def for_user(user):
    """The alerts this person may actually see.

    Filtered here rather than in each route so the badge count and the list
    cannot drift apart. A badge promising three things over a page showing two
    is a small bug of the kind nobody ever reports - they just stop trusting the
    number.
    """
    return [alert for alert in cached_for(user.business_id)
            if alert['kind'] not in ALERT_PERMISSIONS
            or user.can(ALERT_PERMISSIONS[alert['kind']])]


def cached_for(business_id):
    """The alerts themselves, sharing the same per-request cache."""
    from flask import g, has_request_context

    if not has_request_context():
        return for_business(business_id)

    cache = getattr(g, '_alert_cache', None)
    if cache is None:
        cache = g._alert_cache = {}
    if business_id not in cache:
        cache[business_id] = for_business(business_id)
    return cache[business_id]
