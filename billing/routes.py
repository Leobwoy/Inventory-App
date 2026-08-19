"""Subscription pages: what you are on, what it costs, and paying for it.

Two audiences with different powers, which is why the confirmation screen is
gated on being a *platform* admin rather than on a permission. A tenant Owner
holds every permission inside their own business, so a permission-gated confirm
button would let a business switch on its own paid plan.
"""
from decimal import Decimal

from flask import current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from auth.decorators import permission_required
from auth.models import User
from billing import billing_bp, providers
from billing.forms import MomoPaymentForm
from billing.models import PaymentTransaction, Plan, Subscription
from extensions import db
from products.models import Product
from services import billing as billing_service
from services import limits


@billing_bp.route('/')
@login_required
@permission_required('settings.manage')
def overview():
    """The current plan, what it is costing, and what else is available."""
    business_id = current_user.business_id
    subscription = Subscription.query.filter_by(business_id=business_id).first()
    plan = limits.effective_plan(business_id)

    return render_template(
        'billing/overview.html',
        subscription=subscription,
        plan=plan,
        # Only what the plan actually grants right now - a lapsed subscription
        # shows Free here even while its row still names what was bought.
        plans=Plan.query.filter_by(is_public=True).order_by(Plan.sort_order).all(),
        users_used=limits.active_user_count(business_id),
        products_used=limits.active_product_count(business_id),
        # What this plan is currently holding back. The counts above say what is
        # in use; these say what upgrading would give back, which is the number
        # somebody deciding whether to pay actually wants.
        locked_products=Product.query.filter_by(
            business_id=business_id, locked_by_plan=True).count(),
        suspended_users=User.query.filter_by(
            business_id=business_id, is_active=False).count(),
        payments=billing_service.history(business_id),
        provider=providers.active(),
    )


@billing_bp.route('/upgrade/<plan_code>', methods=['GET', 'POST'])
@login_required
@permission_required('settings.manage')
def upgrade(plan_code):
    """Show how to pay, and take the customer's claim that they have.

    Nothing here activates anything. The transaction is recorded as pending and
    a person checks it against the wallet's own statement.
    """
    plan = Plan.query.filter_by(code=plan_code, is_public=True).first_or_404()
    provider = providers.active()

    if plan.price_monthly_ghs is None:
        flash(f'{plan.name} is priced case by case. Get in touch and we will '
              'set it up for you.', 'info')
        return redirect(url_for('billing.overview'))

    if not provider.configured:
        # Better a plain refusal than a page telling someone to pay nobody.
        current_app.logger.error('MOMO_NUMBER / MOMO_NAME are not configured')
        flash('Online payment is not available right now. Please get in touch.', 'warning')
        return redirect(url_for('billing.overview'))

    form = MomoPaymentForm()
    if form.validate_on_submit():
        reference = form.reference.data.strip()

        # Length runs before the strip, so "  ab  " passes a four-character
        # minimum and becomes two. Check what will actually be stored.
        if len(reference) < 4:
            form.reference.errors.append('That does not look like a transaction ID.')
            return render_template('billing/upgrade.html', plan=plan, form=form,
                                   instructions=provider.instructions(plan, form.cycle.data))

        # A cycle the plan has no price for cannot be paid for. The radio hides
        # it, but hiding a control is not enforcing anything.
        if billing_service.price_of(plan, form.cycle.data) is None:
            form.cycle.errors.append('That billing cycle is not available for this plan.')
            return render_template('billing/upgrade.html', plan=plan, form=form,
                                   instructions=provider.instructions(plan, 'monthly'))

        # provider_ref is unique platform-wide, so the same transaction ID
        # cannot buy two subscriptions - including for two different businesses.
        if PaymentTransaction.query.filter_by(provider_ref=reference).first():
            flash('That transaction ID has already been submitted. If you think '
                  'this is wrong, get in touch.', 'danger')
            return render_template('billing/upgrade.html', plan=plan, form=form,
                                   instructions=provider.instructions(plan, form.cycle.data))

        try:
            billing_service.start_payment(
                business_id=current_user.business_id,
                plan=plan,
                cycle=form.cycle.data,
                provider_code=provider.code,
                reference=reference,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('recording a claimed payment failed')
            flash('Something went wrong and your payment was not recorded. '
                  'Please try again.', 'danger')
            return redirect(url_for('billing.overview'))

        flash('Thank you. We will confirm your payment against our mobile money '
              'record and switch your plan on - usually within a few hours.', 'success')
        return redirect(url_for('billing.overview'))

    return render_template('billing/upgrade.html', plan=plan, form=form,
                           instructions=provider.instructions(plan, form.cycle.data or 'monthly'))
