"""Console pages: what needs doing, who the customers are, and what they pay.

Built to grow. Payments are the immediate need, but the point of a console is
that adding the next thing is a route and a template rather than an SSH session
and a SQL prompt.
"""
import datetime
from decimal import Decimal

from flask import (current_app, flash, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import func

from auth.models import Business, User
from products.models import Product
from billing.models import PaymentTransaction, Plan, Subscription
from extensions import db
from platform_console import platform_bp
from platform_console.auth import (current_admin, platform_required, sign_in,
                                   sign_out)
from platform_console.forms import ChangePlanForm, PlatformLoginForm, PaymentActionForm
from platform_console.models import PlatformAdmin
from services import billing as billing_service
from services import limits


@platform_bp.context_processor
def console_context():
    """`platform_admin`, for console templates only.

    Blueprint-scoped rather than app-wide: as an app context processor this ran
    a PlatformAdmin lookup on every render of every tenant page, to populate a
    variable no tenant template reads.
    """
    return {'platform_admin': current_admin()}


# --- getting in -------------------------------------------------------------

@platform_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_admin():
        return redirect(url_for('platform.dashboard'))

    form = PlatformLoginForm()
    if form.validate_on_submit():
        email = (form.email.data or '').strip().lower()
        admin = PlatformAdmin.query.filter(
            func.lower(PlatformAdmin.email) == email).first()

        # One message for every failure. Saying "no such account" tells an
        # attacker which addresses are worth guessing a password for.
        if admin and admin.is_active and admin.check_password(form.password.data):
            sign_in(admin)
            admin.last_login_at = datetime.datetime.utcnow()
            db.session.commit()
            return redirect(url_for('platform.dashboard'))

        flash('Those details are not recognised.', 'danger')

    return render_template('platform/login.html', form=form)


@platform_bp.route('/logout', methods=['POST'])
def logout():
    """POST, not a link: a GET logout can be triggered by anything that renders
    a URL on your behalf, and CSRF protection does not apply to GET."""
    sign_out()
    return redirect(url_for('platform.login'))


# --- the dashboard ----------------------------------------------------------

@platform_bp.route('/')
@platform_required
def dashboard():
    """What needs doing, and how the platform is going.

    Ordered by what the reader can act on: money waiting to be confirmed first,
    then trials about to lapse, which are the two things that are worth
    someone's attention today.
    """
    now = datetime.datetime.utcnow()
    soon = now + datetime.timedelta(days=3)

    pending = billing_service.pending_payments()

    # Trials that lapse within three days: the only list on this page that is a
    # sales prompt rather than a report.
    expiring = (Subscription.query
                .filter(Subscription.status == 'trialing',
                        Subscription.trial_ends_at.isnot(None),
                        Subscription.trial_ends_at <= soon,
                        Subscription.trial_ends_at > now)
                .order_by(Subscription.trial_ends_at.asc())
                .all())

    # Counted and summed in SQL. Walking the rows to read s.plan is a query per
    # subscription, and this is the page that loads most often.
    paying_count, monthly_value = (
        db.session.query(func.count(Subscription.id),
                         func.coalesce(func.sum(Plan.price_monthly_ghs), 0))
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(Subscription.status.in_(('active', 'grace')),
                Subscription.paid_through.isnot(None),
                Subscription.paid_through > now)
        .one())

    # Only the businesses these two lists actually name, not every tenant.
    named = {t.business_id for t in pending} | {s.business_id for s in expiring}
    businesses = ({b.id: b for b in Business.query.filter(Business.id.in_(named)).all()}
                  if named else {})

    return render_template(
        'platform/dashboard.html',
        pending=pending,
        expiring=expiring,
        businesses=businesses,
        total_businesses=Business.query.count(),
        paying_count=paying_count,
        monthly_value=Decimal(monthly_value),
        new_this_month=Business.query.filter(
            Business.created_at >= now - datetime.timedelta(days=30)).count(),
    )


# --- payments ---------------------------------------------------------------

@platform_bp.route('/payments')
@platform_required
def payments():
    """Everything claimed, newest first, whatever its state.

    Rejected and confirmed rows stay visible. A rejected claim is the record of
    someone saying money arrived when it did not, which is exactly the history
    worth being able to look back at.
    """
    state = request.args.get('state', 'pending')
    query = PaymentTransaction.query
    if state in ('pending', 'paid', 'rejected'):
        query = query.filter_by(status=state)

    transactions = query.order_by(PaymentTransaction.created_at.desc()).limit(200).all()
    businesses = {b.id: b for b in Business.query.all()}

    return render_template('platform/payments.html',
                           transactions=transactions, businesses=businesses,
                           state=state, form=PaymentActionForm())


@platform_bp.route('/payments/<int:transaction_id>/<action>', methods=['POST'])
@platform_required
def act_on_payment(transaction_id, action):
    form = PaymentActionForm()
    transaction = PaymentTransaction.query.get_or_404(transaction_id)
    admin = current_admin()

    if not form.validate_on_submit():
        flash('That did not go through. Please try again.', 'danger')
        return redirect(url_for('platform.payments'))

    try:
        if action == 'confirm':
            changed = billing_service.confirm(transaction, confirmed_by=admin.email,
                                              note=form.note.data or None)
            message = ('Payment confirmed and the plan is active.' if changed
                       else 'That payment was already settled.')
        elif action == 'reject':
            reason = (form.note.data or '').strip()
            if not reason:
                flash('A reason is required to reject a payment.', 'danger')
                return redirect(url_for('platform.payments'))
            changed = billing_service.reject(transaction, rejected_by=admin.email,
                                             reason=reason)
            message = ('Payment rejected. The claim is kept on record.' if changed
                       else 'That payment was already settled.')
        else:
            flash('Unknown action.', 'danger')
            return redirect(url_for('platform.payments'))
        db.session.commit()
    except ValueError as error:
        # A domain refusal carries text written for a reader. Anything else is a
        # fault, and its message belongs in the log rather than on the screen.
        db.session.rollback()
        flash(str(error), 'danger')
        return redirect(url_for('platform.payments'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('a console payment action failed')
        flash('Something went wrong and nothing was changed.', 'danger')
        return redirect(url_for('platform.payments'))

    flash(message, 'success')
    return redirect(url_for('platform.payments'))


# --- customers --------------------------------------------------------------

def _shown_status(subscription):
    """The status in effect now, not the one last written.

    Derived rather than stored on purpose: the scheduled job may not have run
    yet, and the console should never be the place a stale row is believed.
    """
    from services import subscriptions as lifecycle

    if subscription is None:
        return None
    return lifecycle.due_transition(subscription) or subscription.status


@platform_bp.route('/businesses')
@platform_required
def businesses():
    """Every tenant, with what they are on and how much of it they use."""
    term = (request.args.get('q', '') or '').strip()
    query = Business.query
    if term:
        query = query.filter(Business.name.ilike(f'%{term}%'))

    found = query.order_by(Business.created_at.desc()).limit(200).all()
    ids = [b.id for b in found]

    # Grouped once for the page. Per-business counts meant four round trips a
    # row, which at 200 rows is 800 queries to draw one table.
    user_counts = dict(
        db.session.query(User.business_id, func.count(User.id))
        .filter(User.business_id.in_(ids), User.is_active.isnot(False))
        .group_by(User.business_id).all()) if ids else {}
    product_counts = dict(
        db.session.query(Product.business_id, func.count(Product.id))
        .filter(Product.business_id.in_(ids), Product.is_active.is_(True))
        .group_by(Product.business_id).all()) if ids else {}
    subscriptions = {s.business_id: s for s in Subscription.query.filter(
        Subscription.business_id.in_(ids)).all()} if ids else {}

    rows = [{
        'business': business,
        # Still per-business: effective_plan reads a subscription's dates and
        # has no batched form. It is memoised per request, so this costs one
        # lookup per business rather than two queries.
        'plan': limits.effective_plan(business.id),
        'subscription': subscriptions.get(business.id),
        # What the status *should* be, given the dates. Reading the stored one
        # showed "Trial" next to a Kiosk plan on the same row - the plan column
        # comes from effective_plan, which had already worked out the trial was
        # over. This is that same answer, so the two columns cannot disagree.
        'status': _shown_status(subscriptions.get(business.id)),
        'users': user_counts.get(business.id, 0),
        'products': product_counts.get(business.id, 0),
    } for business in found]

    return render_template('platform/businesses.html', rows=rows, q=term)


@platform_bp.route('/businesses/<int:business_id>', methods=['GET', 'POST'])
@platform_required
def business_detail(business_id):
    """One tenant, with the ability to put them on a plan by hand.

    Needed for the cases money cannot express: comping an early customer,
    correcting a mistake, extending someone whose payment went astray. Every
    change is written to that business's own audit log, so it is visible to
    them and not only to us.
    """
    business = Business.query.get_or_404(business_id)
    subscription = Subscription.query.filter_by(business_id=business_id).first()
    form = ChangePlanForm()
    form.plan_code.choices = [(p.code, p.name) for p in
                              Plan.query.order_by(Plan.sort_order).all()]

    if form.validate_on_submit():
        plan = Plan.query.filter_by(code=form.plan_code.data).first()
        if plan is None or subscription is None:
            flash('Could not change that plan.', 'danger')
            return redirect(url_for('platform.business_detail', business_id=business_id))

        from services import audit
        before = (subscription.plan.code, subscription.status)
        subscription.plan_id = plan.id
        subscription.status = form.status.data
        if form.days.data:
            subscription.paid_through = (datetime.datetime.utcnow()
                                         + datetime.timedelta(days=int(form.days.data)))
        try:
            audit.log('billing.plan_changed_by_platform', entity_type='business',
                      entity_id=business_id, business_id=business_id, user_id=None,
                      before=before, after=(plan.code, subscription.status),
                      reason=form.reason.data, changed_by=current_admin().email)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('a console plan change failed')
            flash('Something went wrong and nothing was changed.', 'danger')
            return redirect(url_for('platform.business_detail', business_id=business_id))

        flash(f'{business.name} is now on {plan.name}.', 'success')
        return redirect(url_for('platform.business_detail', business_id=business_id))

    if subscription:
        form.plan_code.data = subscription.plan.code
        form.status.data = subscription.status

    return render_template(
        'platform/business_detail.html',
        business=business,
        subscription=subscription,
        plan=limits.effective_plan(business_id),
        owner=User.query.filter_by(business_id=business_id).order_by(User.id).first(),
        staff=User.query.filter_by(business_id=business_id).order_by(User.id).all(),
        users=limits.active_user_count(business_id),
        products=limits.active_product_count(business_id),
        payments=billing_service.history(business_id),
        form=form,
    )


@platform_bp.route('/businesses/<int:business_id>/users/<int:user_id>/reset-password',
                   methods=['POST'])
@platform_required
def reset_tenant_password(business_id, user_id):
    """Issue a tenant a new temporary password. The last way back in.

    An Owner locked out of their own business cannot be helped from inside it —
    they are the one who holds `users.manage`. Without this, the only recovery is
    someone with shell access to the production database, which is not a support
    process.

    Deliberately powerful, so it is deliberately loud: the entry lands in *that
    business's* activity log, naming the admin who did it, where the Owner can
    see it.
    """
    from services import passwords

    user = User.query.filter_by(id=user_id, business_id=business_id).first_or_404()

    # Login refuses a suspended account before it ever checks the password, so
    # resetting one hands over a password that cannot work and reports success.
    # The CLI already refused this; the console did not.
    if not user.is_active:
        flash(f'{user.name} is suspended, so a new password would not let them '
              f'in. Their Owner must reinstate the account first.', 'warning')
        return redirect(url_for('platform.business_detail', business_id=business_id))

    try:
        temporary = passwords.reset(user, by=current_admin().email)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('a console password reset failed')
        flash('Something went wrong and the password was not changed.', 'danger')
        return redirect(url_for('platform.business_detail', business_id=business_id))

    flash(f'Temporary password for {user.name} ({user.email}): {temporary} — '
          f'shown once. They must change it when they sign in.', 'success')
    return redirect(url_for('platform.business_detail', business_id=business_id))
