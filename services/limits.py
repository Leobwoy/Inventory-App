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


def effective_plan(business_id):
    """The plan whose limits actually apply right now.

    A lapsed trial or an expired paid period falls back to Free rather than
    continuing to grant what was never paid for. The status column is not
    rewritten here - that belongs to a scheduled job in Stage 2B - so this stays
    a read-only view that is always correct even if the job has not run.
    """
    subscription = subscription_for(business_id)
    if subscription is None:
        return Plan.query.filter_by(code='free').first()

    now = datetime.utcnow()

    if subscription.status == 'trialing':
        if subscription.trial_ends_at and subscription.trial_ends_at < now:
            return Plan.query.filter_by(code='free').first()
        return subscription.plan

    if subscription.status in ('active', 'grace'):
        if subscription.paid_through:
            grace_deadline = subscription.paid_through + _grace()
            if grace_deadline < now:
                return Plan.query.filter_by(code='free').first()
        return subscription.plan

    # free, cancelled, or anything unrecognised
    if subscription.status == 'free':
        return subscription.plan
    return Plan.query.filter_by(code='free').first()


def _grace():
    from datetime import timedelta
    return timedelta(days=GRACE_DAYS)


def has_feature(code, business_id=None):
    """True if the business's current plan includes `code`."""
    business_id = business_id or _current_business_id()
    if business_id is None:
        return False
    plan = effective_plan(business_id)
    if plan is None:
        return False
    # Trust the seeded feature list, falling back to the tier map if a plan row
    # was created without one.
    return code in (plan.features or features_for_tier(plan.code))


def can_add_user(business_id=None):
    """(allowed, message). Message is None when allowed."""
    from auth.models import User

    business_id = business_id or _current_business_id()
    plan = effective_plan(business_id)
    if plan is None or plan.max_users is None:
        return True, None

    current = User.query.filter_by(business_id=business_id).count()
    if current < plan.max_users:
        return True, None
    return False, (
        f'The {plan.name} plan covers {plan.max_users} '
        f'{"person" if plan.max_users == 1 else "people"}, and you have {current}. '
        'Upgrade to add more staff.'
    )


def can_add_product(business_id=None, adding=1):
    """(allowed, message). `adding` lets a bulk upload check the whole batch."""
    business_id = business_id or _current_business_id()
    plan = effective_plan(business_id)
    if plan is None or plan.max_products is None:
        return True, None

    current = db.session.query(db.func.count(Product.id)).filter(
        Product.business_id == business_id
    ).scalar() or 0

    if current + adding <= plan.max_products:
        return True, None
    return False, (
        f'The {plan.name} plan covers {plan.max_products} products, and you have {current}. '
        'Upgrade to add more.'
    )


def _current_business_id():
    if getattr(current_user, 'is_authenticated', False):
        return current_user.business_id
    return None
