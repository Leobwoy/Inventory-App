"""Messages the platform sends to one business, shown once and then gone.

Separate from `services/notifications.py` on purpose, and the difference is not
cosmetic:

- notifications are **derived**. They work out what is true right now, empty
  themselves when it stops being true, and the inbox that holds them is a paid
  feature.
- notices are **stored**. They record a decision a person made, they do not
  become untrue, and they reach every business on every plan - "your payment was
  rejected" is not something anybody should have to buy a plan to be told.

Both, for a payment: the notice is the popup on Monday morning, the audit entry
is the answer six months later.
"""
from datetime import datetime

from billing.models import BusinessNotice
from extensions import db


def add(business_id, title, body='', level='info'):
    """Queue one notice. Does not commit - the caller owns the transaction."""
    notice = BusinessNotice(business_id=business_id, title=title,
                            body=body or '', level=level)
    db.session.add(notice)
    return notice


def unseen_for(business_id):
    """The oldest notice this business has not closed, or None.

    One at a time. Four modals stacked on a dashboard is not a message, it is an
    obstacle, and the person clicks through all of them without reading any.
    """
    return (BusinessNotice.query
            .filter_by(business_id=business_id, seen_at=None)
            .order_by(BusinessNotice.created_at.asc(), BusinessNotice.id.asc())
            .first())


def mark_seen(business_id, notice_id):
    """Close one notice. Scoped by business, because the id comes from a form."""
    notice = BusinessNotice.query.filter_by(
        id=notice_id, business_id=business_id, seen_at=None).first()
    if notice is None:
        return False
    notice.seen_at = datetime.utcnow()
    return True


def raise_for_payment(transaction, action, admin_email):
    """The notice for a payment the console has just settled.

    Written for the person who sent the money, not for the person who processed
    it: what happened, to which amount, and what it means for them now.
    """
    amount = '{:,.2f}'.format(transaction.amount_ghs or 0)
    plan = transaction.plan.name if transaction.plan else 'your plan'

    if action == 'confirm':
        return add(
            transaction.business_id, level='success',
            title='Payment received',
            body=(f'We have confirmed your payment of GHS {amount}. '
                  f'{plan} is active - everything it covers is switched back on.'))
    return add(
        transaction.business_id, level='danger',
        title='Payment could not be confirmed',
        body=(f'We could not confirm your payment of GHS {amount} for {plan}. '
              'Nothing has been taken. Check the reference you sent and try '
              'again, or reply to us if you believe this is wrong.'))
