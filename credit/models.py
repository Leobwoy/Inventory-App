"""Credit and payment records.

A sale is the debt; payments are what reduces it. The balance is always derived
from those two rather than stored, so it cannot drift out of step the way
Product.quantity_in_stock did before it became a maintained cache (F-12).
"""
from datetime import datetime
from decimal import Decimal

from extensions import db

# How money arrived. momo dominates in this market; the reference field holds the
# transaction ID the customer forwards.
PAYMENT_METHODS = [
    ('cash', 'Cash'),
    ('momo', 'Mobile Money'),
    ('bank', 'Bank transfer'),
    ('cheque', 'Cheque'),
]

# A sale is settled, partly settled, or entirely outstanding.
SETTLEMENT_PAID = 'paid'
SETTLEMENT_PARTIAL = 'partial'
SETTLEMENT_CREDIT = 'credit'


class Payment(db.Model):
    """Money received against a sale.

    Attached to a sale rather than floating against a customer, so every cedi can
    be traced to what it paid for. A customer-level balance is the sum across
    their sales.
    """
    # Mirrors migration f4a82c17d6e9. Declared here too, or a schema built by
    # create_all() differs from the deployed one and autogenerate proposes
    # dropping all four the next time anyone runs it.
    __table_args__ = (
        db.CheckConstraint('amount > 0', name='ck_payment_amount_positive'),
        db.Index('ix_payment_sale', 'sale_id'),
        db.Index('ix_payment_business_customer', 'business_id', 'customer_id'),
        db.Index('ix_payment_business_paid_on', 'business_id', 'paid_on'),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id', ondelete='CASCADE'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))

    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(20), nullable=False, default='cash')
    # The MoMo transaction ID, cheque number or bank reference. Free text because
    # every provider formats it differently, and it is for the human reconciling.
    reference = db.Column(db.String(120))
    paid_on = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)

    recorded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sale = db.relationship('Sale', backref=db.backref(
        'payments', lazy=True, cascade='all, delete-orphan'))
    customer = db.relationship('Customer', backref=db.backref('payments', lazy=True))
    recorded_by_user = db.relationship('User')

    def __repr__(self):
        return f'<Payment {self.amount} {self.method} sale={self.sale_id}>'


def sale_total(sale):
    """What the sale was worth. Summed in Decimal, never float."""
    return sum((item.price_at_sale * item.quantity for item in sale.items), Decimal('0'))


def sale_paid(sale):
    return sum((payment.amount for payment in sale.payments), Decimal('0'))


def sale_balance(sale):
    """Outstanding on this sale. Never negative - an overpayment reads as settled."""
    return max(Decimal('0'), sale_total(sale) - sale_paid(sale))


def settlement_of(total, paid):
    """paid, partial or credit for an already-known pair of amounts.

    Separate from settlement_status so a caller that has summed payments over a
    date window - an as-of statement - can classify with those figures instead
    of the sale's full payment history.
    """
    if paid >= total and total > 0:
        return SETTLEMENT_PAID
    if paid > 0:
        return SETTLEMENT_PARTIAL
    return SETTLEMENT_CREDIT


def settlement_status(sale):
    """paid, partial or credit, derived rather than stored."""
    return settlement_of(sale_total(sale), sale_paid(sale))
