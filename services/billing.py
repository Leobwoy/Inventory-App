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
    """
    if transaction.status == 'paid':
        return False

    subscription = Subscription.query.filter_by(business_id=transaction.business_id).first()
    if subscription is None:
        raise ValueError('That business has no subscription to activate.')

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

    audit.log('billing.payment_confirmed', entity_type='business',
              entity_id=transaction.business_id,
              provider=transaction.provider, reference=transaction.provider_ref,
              amount=str(transaction.amount_ghs), plan=plan.code,
              paid_through=subscription.paid_through.isoformat(),
              confirmed_by=confirmed_by, note=note)
    return True


def reject(transaction, rejected_by, reason):
    """Refuse a claimed payment. The row is kept, never deleted.

    A rejected claim is the record of someone saying money arrived when it did
    not, and that is exactly the history worth keeping.
    """
    if transaction.status == 'paid':
        raise ValueError('That payment was already confirmed.')
    transaction.status = 'rejected'
    audit.log('billing.payment_rejected', entity_type='business',
              entity_id=transaction.business_id,
              reference=transaction.provider_ref, reason=reason,
              rejected_by=rejected_by)


def _plan_for(transaction):
    """The plan a transaction was raised against, matched on what it cost.

    PaymentTransaction records the amount rather than the plan, so the plan is
    recovered from the price and cycle the period length implies.
    """
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
