"""Closing a business account, and everything that belongs to it.

Separate from `services/backup.wipe_business_data`, which clears the operational
rows so a restore can put fresh ones in and deliberately leaves the account, its
users and its audit log standing. This goes further: the business itself, every
staff login, the subscription and the payment record. Nothing is left to find.

**Invariant 10 is not in tension with this.** It says customer data is never
deleted *to enforce a plan limit* - a downgrade removes access, not records,
because the business did not ask for that. This is the business asking, about
its own data, in its own words. The rule protects owners from us; it does not
protect owners from themselves.
"""
from extensions import db
from services import backup


def summarise(business_id):
    """What deleting this account would destroy, counted before anything goes.

    Read-only, and shown on the page next to the confirmation box. A count is
    the difference between "delete my account" and "delete my account, which is
    1,842 sales and 30 customers" - and the second is the one somebody stops to
    read.
    """
    from auth.models import AuditLog, User
    from billing.models import PaymentTransaction

    counts = {}
    for table_name, model, _cols in backup.EXPORT_SPEC:
        counts[table_name] = len(backup._rows_for(model, business_id))
    counts['users'] = User.query.filter_by(business_id=business_id).count()
    counts['audit entries'] = AuditLog.query.filter_by(business_id=business_id).count()
    counts['payments'] = PaymentTransaction.query.filter_by(business_id=business_id).count()
    return {name: n for name, n in counts.items() if n}


def delete_business(business_id, requested_by_email):
    """Erase a business and everything belonging to it. Does not commit.

    Ordered children-first throughout, because every foreign key here is NOT
    NULL with no cascade: deleting a parent first makes the database raise
    rather than tidy up after itself, which is the same reason a product that
    has traded cannot be deleted.

    The record of the deletion goes to the **application log**, not the audit
    table. `AuditLog.business_id` is NOT NULL with a foreign key to the row
    being deleted, so an entry about the deletion cannot outlive it - and an
    entry written before it is deleted along with everything else. Somebody will
    eventually ask what happened to an account, and the server log is the only
    place left that can answer.
    """
    from flask import current_app
    from auth.models import AuditLog, User
    from billing.models import PaymentTransaction, Subscription
    counts = summarise(business_id)

    # 1. Operational rows - products, sales, orders, stock, customers, suppliers.
    backup.wipe_business_data(business_id)

    # 2. Billing. Payments reference the subscription, so they go first.
    PaymentTransaction.query.filter_by(business_id=business_id).delete(
        synchronize_session=False)
    Subscription.query.filter_by(business_id=business_id).delete(
        synchronize_session=False)

    # 3. The audit log. Kept until now so the wipe above is still recorded
    #    against a live business if anything raises and rolls this back.
    AuditLog.query.filter_by(business_id=business_id).delete(
        synchronize_session=False)

    # 4. Every login. Staff first, owner last - not for the database's sake but
    #    so a half-finished delete never leaves staff with access to a business
    #    whose owner is already gone.
    users = User.query.filter_by(business_id=business_id).all()
    for user in sorted(users, key=lambda u: u.is_owner):
        db.session.delete(user)
    db.session.flush()

    # 5. The business itself.
    business = _business_model().query.get(business_id)
    if business is not None:
        db.session.delete(business)

    current_app.logger.warning(
        'business %s deleted at the request of %s; destroyed %s',
        business_id, requested_by_email, counts)
    return counts


def _business_model():
    from auth.models import Business

    return Business
