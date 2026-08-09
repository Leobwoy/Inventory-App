"""The subscription lifecycle: what happens as time passes.

Separate from the two modules either side of it. `services/limits.py` answers
"what does this business have right now"; `services/billing.py` answers "what
did they pay for". This one answers "what has expired", which is the only one of
the three that nothing was asking.

Until now `subscription.status` was written in exactly two places - a confirmed
payment, and a plan changed by hand in the console - so a trial that ended three
weeks ago still read `trialing` forever. The console showed it: Plan "Kiosk"
beside Status "Trial", on the same row, disagreeing with itself.

**The job is not the authority.** `limits.effective_plan()` works entitlement out
from the dates on every read, and stays correct whether or not anything here has
ever run. This module makes the stored status agree with that, and gives the
reminders something to hang off - but access never waits on a scheduled task. A
missed run must not hand out paid features, and must not lock out someone who
paid. On a free tier that sleeps, missed runs are a certainty.

Two triggers, deliberately:

- **Lazily**, when a business uses the app, so the common case is right even if
  nothing is scheduled at all.
- **On a schedule**, which catches the businesses that are *not* logging in -
  precisely the ones worth chasing.
"""
import datetime

from billing.models import Plan, Subscription
from billing.plans import GRACE_DAYS
from extensions import db
from services import audit

#: What each transition means, for the audit entry and any later message.
REASONS = {
    ('trialing', 'free'): 'The free trial ended.',
    ('active', 'grace'): 'The paid period ended; the grace period has started.',
    ('grace', 'free'): 'The grace period ended without a renewal.',
    ('active', 'free'): 'The paid period ended and no end date was recorded.',
}


def _grace_period():
    return datetime.timedelta(days=GRACE_DAYS)


def due_transition(subscription, now=None):
    """The status this subscription should have moved to, or None.

    Mirrors the branches in `limits.effective_plan` exactly. If the two ever
    disagree, the stored status is the one that is wrong - the read path is what
    decides access.
    """
    now = now or datetime.datetime.utcnow()

    if subscription.status == 'trialing':
        # A missing end date denies, the same way effective_plan does.
        if subscription.trial_ends_at is None or subscription.trial_ends_at < now:
            return 'free'
        return None

    if subscription.status == 'active':
        if subscription.paid_through is None:
            return 'free'
        if subscription.paid_through < now:
            return 'grace'
        return None

    if subscription.status == 'grace':
        if subscription.paid_through is None:
            return 'free'
        if subscription.paid_through + _grace_period() < now:
            return 'free'
        return None

    return None


def reconcile(subscription, now=None):
    """Apply one due transition. Returns the new status, or None if nothing was due.

    Does not commit - the caller owns the transaction.

    Downgrading to free rewrites `plan_id` as well as the status, and that is
    load-bearing: `effective_plan` reads a 'free' status as "on the plan named
    here, with no expiry", which is how a comped account works. Leaving a paid
    plan_id in place while flipping the status to free would hand out that plan
    permanently - the exact opposite of a downgrade.
    """
    now = now or datetime.datetime.utcnow()
    target = due_transition(subscription, now)
    if target is None:
        return None

    was = (subscription.status, subscription.plan.code if subscription.plan else None)
    subscription.status = target

    if target == 'free':
        free = Plan.query.filter_by(code='free').first()
        if free is None:
            # Refuse rather than leave a paid plan on a free status.
            raise RuntimeError('No free plan is seeded; cannot downgrade safely.')
        subscription.plan_id = free.id
        subscription.paid_through = None
        subscription.auto_renew = False

    audit.log('billing.subscription_transitioned', entity_type='business',
              entity_id=subscription.business_id,
              business_id=subscription.business_id, user_id=None,
              before=was, after=(target, subscription.plan.code if subscription.plan else None),
              reason=REASONS.get((was[0], target), 'Time passed.'))
    return target


def reconcile_business(business_id, now=None):
    """Reconcile one business. Returns the new status, or None."""
    subscription = Subscription.query.filter_by(business_id=business_id).first()
    if subscription is None:
        return None
    return reconcile(subscription, now)


def pending(now=None):
    """Subscriptions with a transition due, without applying anything.

    Narrowed in SQL so the scheduled run reads only the rows that might move,
    rather than every subscription on the platform.
    """
    now = now or datetime.datetime.utcnow()
    cutoff = now - _grace_period()

    return (Subscription.query
            .filter(db.or_(
                db.and_(Subscription.status == 'trialing',
                        db.or_(Subscription.trial_ends_at.is_(None),
                               Subscription.trial_ends_at < now)),
                db.and_(Subscription.status == 'active',
                        db.or_(Subscription.paid_through.is_(None),
                               Subscription.paid_through < now)),
                db.and_(Subscription.status == 'grace',
                        db.or_(Subscription.paid_through.is_(None),
                               Subscription.paid_through < cutoff)),
            ))
            .all())


def reconcile_all(now=None):
    """Apply every due transition. Returns a summary.

    Each subscription is committed on its own. One business whose row cannot be
    written must not stop the rest from being brought up to date.
    """
    now = now or datetime.datetime.utcnow()
    moved = {}
    failed = []

    for subscription in pending(now):
        business_id = subscription.business_id
        try:
            target = reconcile(subscription, now)
            if target:
                db.session.commit()
                moved[business_id] = target
            else:
                db.session.rollback()
        except Exception:
            db.session.rollback()
            failed.append(business_id)

    return {'moved': moved, 'failed': failed,
            'checked': len(moved) + len(failed)}
