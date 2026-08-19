"""Turning a confirmed payment into an active subscription.

Deliberately separate from the provider. Whether the money was confirmed by a
webhook signature or by a person reading their own mobile money statement, what
happens next is the same - so it lives in one place and gets tested once.
"""
import datetime
from decimal import Decimal

from billing.models import PaymentTransaction, Plan, Subscription
from extensions import db
from services import audit

#: A month, for billing purposes. Calendar months would make a 28-day February
#: cheaper than a 31-day March for the same price, and every customer who
#: noticed would be right to complain.
MONTH_DAYS = 30
YEAR_DAYS = 365


def price_of(plan, cycle):
    """What a plan costs for a cycle, or None when it is not purchasable."""
    if cycle == 'annual':
        return plan.price_annual_ghs
    return plan.price_monthly_ghs


def start_payment(business_id, plan, cycle, provider_code, reference):
    """Record a claimed payment, pending confirmation.

    The amount comes from the Plan, never from the request: a posted price is a
    request to be charged less, and this is the one place that would honour it.
    """
    amount = price_of(plan, cycle)
    if amount is None:
        raise ValueError('That plan is not purchasable online.')

    subscription = Subscription.query.filter_by(business_id=business_id).first()
    days = YEAR_DAYS if cycle == 'annual' else MONTH_DAYS
    starts = _extend_from(subscription)

    transaction = PaymentTransaction(
        business_id=business_id,
        subscription_id=subscription.id if subscription else None,
        plan_id=plan.id,
        provider=provider_code,
        provider_ref=reference,
        amount_ghs=Decimal(amount),
        channel='momo',
        status='pending',
        period_start=starts.date(),
        period_end=(starts + datetime.timedelta(days=days)).date(),
    )
    db.session.add(transaction)
    return transaction


def _extend_from(subscription):
    """Where a new paid period starts.

    From the end of what is already paid for, when that is still in the future.
    Paying early must add time rather than replace it - otherwise renewing a
    week ahead of expiry silently throws that week away.
    """
    now = datetime.datetime.utcnow()
    if subscription and subscription.paid_through and subscription.paid_through > now:
        return subscription.paid_through
    return now


def confirm(transaction, confirmed_by, note=None):
    """Mark a payment received and move the subscription onto its plan.

    Idempotent: confirming twice does not buy a second month. The guard matters
    because the obvious human error here is double-clicking, and the obvious
    machine one is a webhook delivered twice.

    Only a *pending* transaction may be confirmed. Checking for 'paid' alone
    would leave a rejected claim confirmable - so refusing a fraudulent payment
    and then confirming it by accident would grant the plan anyway.
    """
    if transaction.status != 'pending':
        return False

    # Lock the subscription before reading paid_through, because what follows is
    # read-then-write on a shared row (invariant 9). Two confirmations landing
    # together would otherwise both extend from the same starting point, and one
    # customer's paid month would vanish.
    subscription = (Subscription.query
                    .filter_by(business_id=transaction.business_id)
                    .with_for_update()
                    .first())
    if subscription is None:
        raise ValueError('That business has no subscription to activate.')

    # Re-read the transaction under a lock and check again: between the caller's
    # read and this line another request may have confirmed it.
    locked = (PaymentTransaction.query
              .filter_by(id=transaction.id)
              .with_for_update()
              .one())
    if locked.status != 'pending':
        return False
    transaction = locked

    plan = _plan_for(transaction)
    days = (transaction.period_end - transaction.period_start).days

    subscription.plan_id = plan.id
    subscription.status = 'active'
    subscription.paid_through = _extend_from(subscription) + datetime.timedelta(days=days)
    subscription.provider = transaction.provider
    # Mobile money has no reusable authorisation in Ghana, so nothing here can
    # charge them again. Renewal is a reminder, not a debit.
    subscription.auto_renew = False

    transaction.status = 'paid'
    transaction.subscription_id = subscription.id

    # business_id and user_id passed explicitly. audit.log otherwise infers them
    # from current_user, and the console has no current_user - so a payment
    # confirmed there was silently not recorded at all. Money moving with no
    # trail is the one thing this table exists to prevent.
    audit.log('billing.payment_confirmed', entity_type='business',
              entity_id=transaction.business_id,
              business_id=transaction.business_id, user_id=None,
              provider=transaction.provider, reference=transaction.provider_ref,
              amount=str(transaction.amount_ghs), plan=plan.code,
              paid_through=subscription.paid_through.isoformat(),
              confirmed_by=confirmed_by, note=note)
    return True


def reject(transaction, rejected_by, reason):
    """Refuse a claimed payment. The row is kept, never deleted.

    A rejected claim is the record of someone saying money arrived when it did
    not, and that is exactly the history worth keeping.

    Returns True when this call is the one that rejected it. Mirrors confirm():
    the state is re-read under a lock rather than trusted from the caller's
    copy, so a rejection racing a confirmation cannot both land, and a second
    rejection does not write a second audit entry for the same event.
    """
    if transaction.status != 'pending':
        return False

    locked = (PaymentTransaction.query
              .filter_by(id=transaction.id)
              .with_for_update()
              .one())
    if locked.status != 'pending':
        return False

    locked.status = 'rejected'
    audit.log('billing.payment_rejected', entity_type='business',
              entity_id=locked.business_id,
              business_id=locked.business_id, user_id=None,
              reference=locked.provider_ref, reason=reason,
              rejected_by=rejected_by)
    return True


def _plan_for(transaction):
    """The plan a transaction was raised against.

    Read from the transaction, which records it. The fallback matches on price
    and exists only for rows written before plan_id did - a lookup that breaks
    the moment a price changes, which is exactly why the column was added.
    """
    if transaction.plan_id:
        plan = Plan.query.get(transaction.plan_id)
        if plan:
            return plan

    days = (transaction.period_end - transaction.period_start).days
    annual = days > 60
    for plan in Plan.query.filter_by(is_public=True).all():
        price = plan.price_annual_ghs if annual else plan.price_monthly_ghs
        if price is not None and Decimal(price) == Decimal(transaction.amount_ghs):
            return plan
    raise ValueError('No plan matches that payment amount.')


def pending_payments():
    """Claimed but unconfirmed, oldest first - the order to work through."""
    return (PaymentTransaction.query
            .filter_by(status='pending')
            .order_by(PaymentTransaction.created_at.asc())
            .all())


def history(business_id):
    return (PaymentTransaction.query
            .filter_by(business_id=business_id)
            .order_by(PaymentTransaction.created_at.desc())
            .all())
