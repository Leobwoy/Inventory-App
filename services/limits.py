"""What a business's plan allows.

Separate from permissions on purpose. `auth/decorators.permission_required` asks
whether this *person* may act; the checks here ask whether this *business* has
paid for the capability. Both apply, and neither implies the other.

Limit breaches are never a 403. Hitting a plan ceiling is a sales conversation,
not a security event, so callers surface an upgrade prompt instead.
"""
from datetime import datetime

from flask_login import current_user

from billing.models import Plan, Subscription
from billing.plans import GRACE_DAYS, features_for_tier
from extensions import db
from products.models import Product


class PlanLimitReached(Exception):
    """A plan ceiling was hit. Carries a message written for a business owner."""

    def __init__(self, message, limit=None, current=None):
        self.limit = limit
        self.current = current
        super().__init__(message)


def subscription_for(business_id):
    return Subscription.query.filter_by(business_id=business_id).first()


def _request_cached_plan(business_id):
    """effective_plan, memoised on the request.

    Outside a request context - a CLI command, a test calling directly - this is
    just effective_plan, because there is nowhere safe to cache and a long-lived
    cache would go stale the moment a plan changed.
    """
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return effective_plan(business_id)
    except ImportError:
        return effective_plan(business_id)

    cache = getattr(g, '_plan_cache', None)
    if cache is None:
        cache = g._plan_cache = {}
    if business_id not in cache:
        cache[business_id] = effective_plan(business_id)
    return cache[business_id]


def effective_plan(business_id):
    """The plan whose limits actually apply right now.

    A lapsed trial or an expired paid period falls back to Free rather than
    continuing to grant what was never paid for.

    Deliberately read-only: the status column is rewritten by
    services/subscriptions.py, on a schedule and on use. Keeping that out of
    here is what makes this correct whether or not the job has run - and on a
    free instance that sleeps, a run that never happened is a certainty rather
    than an edge case. If the two ever disagree, this one is right.
    """
    subscription = subscription_for(business_id)
    if subscription is None:
        return Plan.query.filter_by(code='free').first()

    now = datetime.utcnow()


    free = Plan.query.filter_by(code='free').first()

    # A missing date denies, it does not grant. Reading a null as "no expiry"
    # means one row written without an end date entitles a business to a paid
    # plan permanently and silently - and the only way anyone finds out is by
    # noticing the money never arrived.
    if subscription.status == 'trialing':
        if subscription.trial_ends_at is None or subscription.trial_ends_at < now:
            return free
        return subscription.plan

    if subscription.status in ('active', 'grace'):
        if subscription.paid_through is None:
            return free
        if subscription.paid_through + _grace() < now:
            return free
        return subscription.plan

    # free, cancelled, or anything unrecognised
    if subscription.status == 'free':
        return subscription.plan
    return free


def _grace():
    from datetime import timedelta
    return timedelta(days=GRACE_DAYS)


def has_feature(code, business_id=None):
    """True if the business's current plan includes `code`.

    The resolved plan is cached for the life of the request. Templates gate
    navigation, scripts and whole sections on this, so one page render asks the
    same question a dozen times - and every ask was two queries. A plan cannot
    change midway through rendering a page, so re-reading it is pure cost.
    """
    business_id = business_id or _current_business_id()
    if business_id is None:
        return False
    plan = _request_cached_plan(business_id)
    if plan is None:
        return False
    # Trust the seeded feature list, falling back to the tier map if a plan row
    # was created without one.
    return code in (plan.features or features_for_tier(plan.code))


def active_user_count(business_id):
    """Suspended staff hold no seat - they cannot log in."""
    from auth.models import User

    return db.session.query(db.func.count(User.id)).filter(
        User.business_id == business_id,
        User.is_active.isnot(False),
    ).scalar() or 0


def active_product_count(business_id):
    """Only products that can actually be sold count against the plan.

    Counting *every* row would let a customer buy one month of a large plan,
    bulk-load a catalogue, drop to the free tier and keep trading on all of it -
    and would also punish a paying customer who retires old lines, since those
    would still consume the allowance.
    """
    return db.session.query(db.func.count(Product.id)).filter(
        Product.business_id == business_id,
        Product.is_active.isnot(False),
    ).scalar() or 0


def can_add_user(business_id=None):
    """(allowed, message). Message is None when allowed."""
    business_id = business_id or _current_business_id()
    plan = effective_plan(business_id)
    if plan is None or plan.max_users is None:
        return True, None

    current = active_user_count(business_id)
    if current < plan.max_users:
        return True, None
    return False, (
        f'The {plan.name} plan covers {plan.max_users} '
        f'{"person" if plan.max_users == 1 else "people"}, and you have {current}. '
        'Upgrade to add more staff, or suspend someone first.'
    )


def can_add_product(business_id=None, adding=1):
    """(allowed, message). `adding` lets a bulk upload check the whole batch.

    Also gates *reactivating* a product, since switching one back on consumes the
    allowance exactly as creating one does.
    """
    business_id = business_id or _current_business_id()
    plan = effective_plan(business_id)
    if plan is None or plan.max_products is None:
        return True, None

    current = active_product_count(business_id)
    if current + adding <= plan.max_products:
        return True, None
    return False, (
        f'The {plan.name} plan covers {plan.max_products} active products, and you have '
        f'{current}. Upgrade to add more, or deactivate a product you no longer stock.'
    )


def _current_business_id():
    if getattr(current_user, 'is_authenticated', False):
        return current_user.business_id
    return None


# --- bringing a business into line after a downgrade -------------------------

def over_limit(business_id=None):
    """How far past its plan a business currently is.

    `{'products': 380, 'users': 14}`, counting only what is actually over. Read
    only - it says nothing about whether anything has been done about it, which
    is what lets the same figures drive both the enforcement below and the
    upgrade prompt somebody reads.
    """
    business_id = business_id or _current_business_id()
    plan = effective_plan(business_id)
    if plan is None:
        return {}

    over = {}
    if plan.max_products is not None:
        excess = active_product_count(business_id) - plan.max_products
        if excess > 0:
            over['products'] = excess
    if plan.max_users is not None:
        excess = active_user_count(business_id) - plan.max_users
        if excess > 0:
            over['users'] = excess
    return over


def enforce_plan_limits(business_id, actor_id=None):
    """Bring a business within its plan. Returns what was switched off.

    Invariant 10 has said since it was written that a downgrade "removes access,
    not records: products deactivate, staff suspend, nothing is destroyed". That
    described an intention nobody had built - the caps were only ever consulted
    when *adding* something, so a Distributor with four hundred products who
    dropped to Kiosk kept all four hundred active and sellable. This is the
    invariant becoming true.

    Three rules hold it together:

    **It only ever takes access away, never gives it back.** Upgrading does not
    resurrect anything: a product the owner retired on purpose must not reappear
    in their catalogue because they bought a bigger plan, and only they know
    which of the four hundred they actually want. So this is safe to call on any
    plan change in either direction, and on a schedule.

    **The Owner is never suspended.** Kiosk has one seat, so a literal reading of
    "suspend everyone over the cap" locks the last person out of a business that
    still owes money - and `auth/routes.py` refuses to suspend an Owner anyway.
    The Owner holds the seat; everyone else goes.

    **Nothing is deleted.** Deactivated products stay in the catalogue, visible
    and marked, and suspended staff keep their accounts and their history. Every
    past sale, order and report is untouched, because the records are the
    business's and the plan only governs what can be done with them today.
    """
    from auth.models import User
    from services import audit

    plan = effective_plan(business_id)
    if plan is None:
        return {}

    switched_off = {}

    if plan.max_products is not None:
        # Newest kept, oldest retired. Any rule here is arbitrary and this one is
        # at least predictable and stable: it does not reshuffle each time it
        # runs. A kinder rule would keep whatever has sold most recently; it is
        # noted in the tracker rather than guessed at here.
        keep = [row.id for row in
                Product.query.with_entities(Product.id)
                .filter(Product.business_id == business_id,
                        Product.is_active.isnot(False))
                .order_by(Product.id.desc())
                .limit(plan.max_products).all()]
        retired = (Product.query
                   .filter(Product.business_id == business_id,
                           Product.is_active.isnot(False),
                           Product.id.notin_(keep) if keep else sa_true())
                   .all())
        for product in retired:
            product.is_active = False
            product.locked_by_plan = True
        if retired:
            switched_off['products'] = [p.sku for p in retired]

    if plan.max_users is not None:
        # Ordered so the Owner keeps a seat and, on Kiosk's single seat, is the
        # only one who does. Sorted in Python because `is_owner` is derived from
        # the role relationship rather than stored - there is no column to order
        # by, and a business holds at most fifteen people.
        staff = sorted(
            User.query.filter(User.business_id == business_id,
                              User.is_active.isnot(False)).all(),
            key=lambda u: (not u.is_owner, u.id))
        suspended = [u for u in staff[plan.max_users:] if not u.is_owner]
        for user in suspended:
            user.is_active = False
        if suspended:
            switched_off['users'] = [u.email for u in suspended]

    if switched_off:
        audit.log('billing.limits_enforced', entity_type='business',
                  entity_id=business_id, business_id=business_id,
                  user_id=actor_id, plan=plan.code, **switched_off)
    return switched_off


def sa_true():
    """A always-true clause, for the case where a plan allows nothing at all."""
    from sqlalchemy import true

    return true()
