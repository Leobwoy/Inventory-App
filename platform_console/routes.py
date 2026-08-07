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
from billing.models import PaymentTransaction, Plan, Subscription
from extensions import db
from platform_console import platform_bp
from platform_console.auth import (current_admin, platform_required, sign_in,
                                   sign_out)
from platform_console.forms import ChangePlanForm, PlatformLoginForm, PaymentActionForm
from platform_console.models import PlatformAdmin
from services import billing as billing_service
from services import limits


@platform_bp.app_context_processor
def console_context():
    """`platform_admin` in every template, so a layout can branch on it."""
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


@platform_bp.route('/logout')
def logout():
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

    paying = (Subscription.query
              .filter(Subscription.status.in_(('active', 'grace')),
                      Subscription.paid_through.isnot(None),
                      Subscription.paid_through > now)
              .all())
    monthly_value = sum(
        (Decimal(s.plan.price_monthly_ghs or 0) for s in paying), Decimal('0'))

    businesses = {b.id: b for b in Business.query.all()}

    return render_template(
        'platform/dashboard.html',
        pending=pending,
        expiring=expiring,
        businesses=businesses,
        total_businesses=len(businesses),
        paying_count=len(paying),
        monthly_value=monthly_value,
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
            billing_service.reject(transaction, rejected_by=admin.email, reason=reason)
            message = 'Payment rejected. The claim is kept on record.'
        else:
            flash('Unknown action.', 'danger')
            return redirect(url_for('platform.payments'))
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        current_app.logger.exception('a console payment action failed')
        flash(f'Could not complete that: {error}', 'danger')
        return redirect(url_for('platform.payments'))

    flash(message, 'success')
    return redirect(url_for('platform.payments'))


# --- customers --------------------------------------------------------------

@platform_bp.route('/businesses')
@platform_required
def businesses():
    """Every tenant, with what they are on and how much of it they use."""
    term = (request.args.get('q', '') or '').strip()
    query = Business.query
    if term:
        query = query.filter(Business.name.ilike(f'%{term}%'))

    rows = []
    for business in query.order_by(Business.created_at.desc()).limit(200).all():
        rows.append({
            'business': business,
            'plan': limits.effective_plan(business.id),
            'subscription': Subscription.query.filter_by(business_id=business.id).first(),
            'users': limits.active_user_count(business.id),
            'products': limits.active_product_count(business.id),
        })

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
        audit.log('billing.plan_changed_by_platform', entity_type='business',
                  entity_id=business_id, business_id=business_id, user_id=None,
                  before=before, after=(plan.code, subscription.status),
                  reason=form.reason.data, changed_by=current_admin().email)
        db.session.commit()
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
        users=limits.active_user_count(business_id),
        products=limits.active_product_count(business_id),
        payments=billing_service.history(business_id),
        form=form,
    )
