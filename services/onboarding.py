"""What a new business still has to do, worked out from what it has done.

Derived, never stored — the same rule as `services/notifications.py`, for the
same reason. A stored checklist can be ticked while the thing is not true, and a
dismissed one goes on saying "all set" to a business with no products in it. Here
a step is done because the data says so, and undoing the work un-ticks it.

The order is the order the app actually forces: you cannot receive stock without
a purchase order, and you cannot sell what you have not received. A new owner who
follows this list top to bottom never hits a dead end, which is the whole point —
the first version of this app could not save a single product, and the reason was
invisible from the dashboard.

Nothing here is a tour. A modal sequence is a lot of JavaScript for something
people click past, and it teaches nothing because it appears before the screen it
describes means anything.
"""
from extensions import db
from products.models import Product, Supplier
from purchases.models import PurchaseOrder
from sales.models import Sale


def _exists(model, business_id, *conditions):
    """An EXISTS clause, not a row and not a count.

    The database stops at the first match; a count keeps going, and loading the
    rows to look at them in Python is how the dashboard came to run a query per
    product the first time round (F-14).
    """
    return (db.session.query(model.id)
            .filter(model.business_id == business_id, *conditions)
            .exists())


def steps(business_id):
    """The setup steps, in order, each with whether it is done.

    All five answered in **one** query. Five separate `EXISTS` calls put the
    dashboard over its query budget the moment this shipped, and the dashboard is
    the page that renders most — the test that caught it exists because an
    earlier version of this page ran a query per product.

    `endpoint`/`params` rather than a built URL, so this stays callable outside a
    request — the same convention as the alerts.
    """
    has_product, has_supplier, has_order, has_stock, has_sale = db.session.query(
        _exists(Product, business_id, Product.is_active.is_(True)),
        _exists(Supplier, business_id),
        _exists(PurchaseOrder, business_id),
        _exists(Product, business_id, Product.quantity_in_stock > 0),
        _exists(Sale, business_id),
    ).one()

    return [
        {'key': 'product', 'done': has_product,
         'title': 'Add your first product',
         'detail': 'What you sell, with its price.',
         'endpoint': 'products.add_product', 'params': {}},
        {'key': 'supplier', 'done': has_supplier,
         'title': 'Add a supplier',
         'detail': 'Who you buy from. Needed before you can order.',
         'endpoint': 'products.add_supplier', 'params': {}},
        {'key': 'order', 'done': has_order,
         'title': 'Raise a purchase order',
         'detail': 'What you are buying, and at what cost.',
         'endpoint': 'purchases.add_purchase', 'params': {}},
        {'key': 'stock', 'done': has_stock,
         'title': 'Receive the goods',
         'detail': 'Stock only enters here, so nothing can be sold until it does.',
         'endpoint': 'purchases.list_purchases', 'params': {}},
        {'key': 'sale', 'done': has_sale,
         'title': 'Record a sale',
         'detail': 'The thing everything else exists for.',
         'endpoint': 'sales.add_sale', 'params': {}},
    ]


def progress(business_id):
    """(done, total). Used for the bar and to decide whether to show anything."""
    found = steps(business_id)
    return sum(1 for s in found if s['done']), len(found)


def next_step(business_id):
    """The first thing not yet done, or None. One instruction beats five."""
    for step in steps(business_id):
        if not step['done']:
            return step
    return None


def is_complete(business_id):
    done, total = progress(business_id)
    return done == total


def state_for(business_id):
    """Everything the dashboard card needs, in one pass.

    One call rather than four, because each of the helpers above walks the same
    tables and this renders on the busiest page in the app.
    """
    found = steps(business_id)
    done = sum(1 for s in found if s['done'])
    return {
        'steps': found,
        'done': done,
        'total': len(found),
        'complete': done == len(found),
        'next': next((s for s in found if not s['done']), None),
        # Nothing done at all means they have just arrived, and the card leads
        # with a welcome rather than a progress bar reading zero.
        'fresh': done == 0,
    }


#: How long after a trial ends to keep explaining what happened. The moment that
#: matters is the first login after the downgrade; a month later it is nagging.
ENDED_NOTICE_DAYS = 14


def trial_state(business_id):
    """What to say about the trial right now, or None if there is nothing to say.

    Three phases, and only three, because a banner that is always present is a
    banner nobody reads:

    - `trialing` — a plain count of days left.
    - `ended` — said once the downgrade has happened, for a fortnight. A customer
      who discovers a downgrade by finding a feature missing does not come back;
      one who is told plainly has a decision to make.
    - nothing at all, for a paying customer.

    Deliberately quiet about the free tier while the trial is running. It is
    listed on the billing page for anyone who looks, and naming it here would
    answer "what happens if I do nothing?" at the exact moment we would rather
    they thought about paying.
    """
    import datetime

    from billing.models import Subscription
    from services import limits

    subscription = Subscription.query.filter_by(business_id=business_id).first()
    if subscription is None:
        return None

    # is_trialing, not status == 'trialing': the status is only rewritten when
    # the lifecycle job runs, so a lapsed trial can still read `trialing` for a
    # while. days_left clamps at zero, so the countdown would sit on "0 days
    # left" indefinitely rather than saying the trial is over.
    if subscription.is_trialing:
        return {'phase': 'trialing', 'days': subscription.days_left}

    plan = limits.effective_plan(business_id)
    if plan is None or plan.code != 'free' or not subscription.trial_ends_at:
        # Paying, or comped onto a real plan. `status == 'free'` alone is not
        # enough to conclude a trial lapsed - a comped account reads exactly the
        # same, and telling those customers their trial ran out would be wrong.
        return None

    now = datetime.datetime.utcnow()
    # The end has to have actually happened. Without this a trial dated in the
    # future gives a negative `since`, which is trivially less than the notice
    # window - so the page would tell someone their trial had ended while it was
    # still running.
    if subscription.trial_ends_at > now:
        return None

    since = now - subscription.trial_ends_at
    if since > datetime.timedelta(days=ENDED_NOTICE_DAYS):
        return None
    return {'phase': 'ended', 'plan': plan}
