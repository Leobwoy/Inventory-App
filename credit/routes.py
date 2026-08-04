from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth.decorators import permission_required, requires_feature
from credit.forms import PaymentForm
from credit.models import Payment, sale_balance, sale_paid, sale_total, settlement_status
from extensions import db
from sales.models import Customer, Sale
from services import audit, credit

credit_bp = Blueprint('credit', __name__)


@credit_bp.route('/')
@login_required
@permission_required('credit.view')
@requires_feature('credit_ledger')
def dashboard():
    """Who owes money, biggest debt first - the order calls get made in."""
    business_id = current_user.business_id
    rows = credit.ageing(business_id)
    return render_template(
        'credit/dashboard.html',
        rows=rows,
        bucket_totals=credit.bucket_totals(rows),
        buckets=[label for _l, _h, label in credit.AGEING_BUCKETS],
        total=sum((r['total'] for r in rows), credit.Decimal('0')),
    )


@credit_bp.route('/customer/<int:customer_id>')
@login_required
@permission_required('credit.view')
@requires_feature('credit_ledger')
def customer_statement(customer_id):
    """Every sale and payment for one customer, with a running balance."""
    customer = Customer.query.filter_by(
        id=customer_id, business_id=current_user.business_id).first_or_404()
    return render_template(
        'credit/statement.html',
        customer=customer,
        events=credit.statement(current_user.business_id, customer_id),
        balance=credit.customer_balance(current_user.business_id, customer_id),
        outstanding=credit.outstanding_sales(current_user.business_id, customer_id),
    )


@credit_bp.route('/walk-ins')
@login_required
@permission_required('credit.view')
@requires_feature('credit_ledger')
def walk_in_sales():
    """Outstanding walk-in sales, one row each.

    The ageing table groups by customer, so walk-ins collapse into a single row
    with no customer to link to - leaving money that is owed with no way to open
    it or settle it.
    """
    rows = credit.walk_in_sales(current_user.business_id)
    return render_template(
        'credit/walk_ins.html',
        rows=rows,
        total=sum((balance for _s, _t, _p, balance in rows), credit.Decimal('0')),
    )


@credit_bp.route('/sale/<int:sale_id>/pay', methods=['GET', 'POST'])
@login_required
@permission_required('credit.record_payment')
@requires_feature('credit_ledger')
def record_payment(sale_id):
    sale = Sale.query.filter_by(
        id=sale_id, business_id=current_user.business_id).first_or_404()

    total, paid = sale_total(sale), sale_paid(sale)
    balance = sale_balance(sale)

    form = PaymentForm()
    if request.method == 'GET':
        form.paid_on.data = date.today()
        form.amount.data = balance          # settling in full is the common case

    if form.validate_on_submit():
        amount = form.amount.data
        if amount > balance:
            # Accepting more than is owed would put the customer in credit with
            # nothing to apply it to, and read as a negative debt on the ageing
            # report. Refuse and say what the actual figure is.
            flash(f'That is more than the {balance} outstanding on this sale.', 'danger')
            return render_template('credit/payment.html', form=form, sale=sale,
                                   total=total, paid=paid, balance=balance)
        if form.paid_on.data > date.today():
            flash('A payment cannot be dated in the future.', 'danger')
            return render_template('credit/payment.html', form=form, sale=sale,
                                   total=total, paid=paid, balance=balance)

        try:
            payment = Payment(
                business_id=current_user.business_id,
                sale_id=sale.id,
                customer_id=sale.customer_id,
                amount=amount,
                method=form.method.data,
                reference=(form.reference.data or '').strip() or None,
                paid_on=form.paid_on.data,
                notes=form.notes.data,
                recorded_by=current_user.id,
            )
            db.session.add(payment)
            db.session.flush()

            audit.log('payment.record', entity_type='sale', entity_id=sale.id,
                      amount=str(amount), method=payment.method,
                      reference=payment.reference,
                      balance_after=str(balance - amount))
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('recording a payment failed')
            flash('Something went wrong and the payment was not saved.', 'danger')
            return render_template('credit/payment.html', form=form, sale=sale,
                                   total=total, paid=paid, balance=balance)

        remaining = balance - amount
        if remaining > 0:
            flash(f'Payment of {amount} recorded. {remaining} still outstanding.', 'success')
        else:
            flash(f'Payment of {amount} recorded. This sale is now settled.', 'success')
        return redirect(url_for('credit.dashboard'))

    return render_template('credit/payment.html', form=form, sale=sale,
                           total=total, paid=paid, balance=balance)


@credit_bp.route('/payment/<int:payment_id>/delete', methods=['POST'])
@login_required
@permission_required('credit.record_payment')
@requires_feature('credit_ledger')
def delete_payment(payment_id):
    """Reverse a payment entered in error. Audited, because it moves money."""
    payment = Payment.query.filter_by(
        id=payment_id, business_id=current_user.business_id).first_or_404()
    sale_id = payment.sale_id

    audit.log('payment.delete', entity_type='sale', entity_id=sale_id,
              amount=str(payment.amount), method=payment.method,
              reference=payment.reference, paid_on=str(payment.paid_on))
    db.session.delete(payment)
    db.session.commit()
    flash('Payment reversed.', 'info')
    return redirect(request.referrer or url_for('credit.dashboard'))
