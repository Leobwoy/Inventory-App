"""Subscriptions and plan limits.

Deliberately separate from the domain modules: what a business is allowed to do
(billing) is a different question from who is allowed to do it (permissions), and
conflating them makes both harder to reason about.

Payments go through billing/providers.py, which exists so that "did the money
arrive?" is the only thing that varies between a human reading a mobile money
statement and a signed Paystack webhook. Everything after that answer is shared.
"""
from flask import Blueprint

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

from . import routes  # noqa: E402,F401


@billing_bp.before_app_request
def reconcile_on_use():
    """Bring this business's subscription up to date, at most once a day.

    Throttled through the session rather than run per request: the check would
    otherwise cost a query on all fifty-odd routes to write something on
    approximately none of them. Once a day per signed-in user is enough, because
    a transition only ever becomes due once.

    Nothing here decides access - `limits.effective_plan` already had that right
    before this existed. This only stops the stored status disagreeing with it.
    """
    import datetime

    from flask import session
    from flask_login import current_user

    if not getattr(current_user, 'is_authenticated', False):
        return

    today = datetime.date.today().isoformat()
    if session.get('subscription_checked') == today:
        return
    session['subscription_checked'] = today

    from extensions import db
    from services import subscriptions

    try:
        if subscriptions.reconcile_business(current_user.business_id):
            db.session.commit()
    except Exception:
        # A failed reconcile must never break the page someone asked for. The
        # scheduled run will pick it up, and access was never waiting on it.
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception('lazy subscription reconcile failed')
