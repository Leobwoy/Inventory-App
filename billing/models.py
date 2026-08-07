"""Subscription state.

Prepaid billing periods, not auto-renewing subscriptions. Paystack documents that
mobile money cannot make recurring charges in Ghana - only card authorisations
are reusable - and this market pays by MoMo. So `paid_through` is the field that
matters: a business buys a period, and the system drives reminders towards its
expiry rather than assuming a charge will succeed on the day.
"""
import json
from datetime import datetime

from extensions import db


class Plan(db.Model):
    """A purchasable tier. Seeded from billing/plans.py, editable in the database."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)

    # Null price means "contact us" - the Custom plan is negotiated, not listed.
    price_monthly_ghs = db.Column(db.Numeric(10, 2))
    price_annual_ghs = db.Column(db.Numeric(10, 2))

    # Null limit means unlimited. Metering is on users and products only, never
    # on transaction volume: a wholesaler doing 200 sales a day would breach any
    # sane cap, and throttling the busiest customer is the worst possible failure.
    max_users = db.Column(db.Integer)
    max_products = db.Column(db.Integer)

    features_json = db.Column(db.Text)
    is_public = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    subscriptions = db.relationship('Subscription', backref='plan', lazy=True)

    @property
    def features(self):
        return set(json.loads(self.features_json)) if self.features_json else set()

    def __repr__(self):
        return f'<Plan {self.code}>'


class Subscription(db.Model):
    """One per business. Its status decides what the business may do."""
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, unique=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'), nullable=False)

    # trialing -> active -> grace -> free, or cancelled at any point.
    status = db.Column(db.String(20), nullable=False, default='trialing')
    trial_ends_at = db.Column(db.DateTime)
    paid_through = db.Column(db.DateTime)
    billing_cycle = db.Column(db.String(10), default='monthly')   # monthly | annual

    # Card only. MoMo cannot be charged again without the customer approving on
    # their handset, so this stays false for most of this market.
    auto_renew = db.Column(db.Boolean, nullable=False, default=False)
    provider = db.Column(db.String(30))
    provider_customer_ref = db.Column(db.String(120))
    provider_authorization_code = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('subscription', uselist=False))
    transactions = db.relationship('PaymentTransaction', backref='subscription', lazy=True)

    @property
    def is_trialing(self):
        return self.status == 'trialing' and not self.trial_expired

    @property
    def trial_expired(self):
        return bool(self.trial_ends_at and self.trial_ends_at < datetime.utcnow())

    @property
    def days_left(self):
        """Days remaining on the trial or the paid period, or None if neither applies."""
        deadline = self.trial_ends_at if self.status == 'trialing' else self.paid_through
        if not deadline:
            return None
        return max(0, (deadline - datetime.utcnow()).days)

    def __repr__(self):
        return f'<Subscription business={self.business_id} {self.status}>'


class PaymentTransaction(db.Model):
    """A single payment attempt. Written by the provider webhook in Stage 2B."""
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'))

    # What was bought. Stored rather than inferred from the amount: prices
    # change, and a payment confirmed after a price rise would otherwise match
    # no plan at all - or the wrong one, if two plans ever share a price.
    plan_id = db.Column(db.Integer, db.ForeignKey('plan.id'))
    plan = db.relationship('Plan')

    provider = db.Column(db.String(30), nullable=False)
    provider_ref = db.Column(db.String(120), nullable=False, unique=True)
    amount_ghs = db.Column(db.Numeric(10, 2), nullable=False)
    channel = db.Column(db.String(20))          # momo | card | bank_transfer
    status = db.Column(db.String(20), nullable=False, default='pending')

    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    raw_payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<PaymentTransaction {self.provider_ref} {self.status}>'
