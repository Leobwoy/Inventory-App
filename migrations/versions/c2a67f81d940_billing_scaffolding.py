"""billing: plans, subscriptions and payment transactions

Scaffolding only - no payment provider code. The models and seeded plans land
now, while Stage 1 is already touching every route, because retrofitting metering
across the application later means a second pass over all of it.

Prepaid billing periods, not auto-renewing subscriptions: Paystack documents that
mobile money cannot be charged recurrently in Ghana, and this market pays by MoMo.

Revision ID: c2a67f81d940
Revises: b8f34d0a51e7
Create Date: 2026-08-03

"""
import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c2a67f81d940'
down_revision = 'b8f34d0a51e7'
branch_labels = None
depends_on = None


# Snapshot of billing/plans.py at this revision. Inlined deliberately: a
# migration must be a fixed point in history, not something that changes
# behaviour when the application's catalogue is later edited.
FEATURES = {
    'purchase_orders': 'basic',
    'exports.csv': 'basic',
    'exports.all': 'standard',
    'credit_ledger': 'standard',
    'uom_conversion': 'standard',
    'expiry_alerts': 'standard',
    'offline': 'standard',
    'notifications': 'standard',
    'supplier_scorecards': 'advanced',
    'price_comparison': 'advanced',
    'margin_reports': 'advanced',
    'audit_log': 'advanced',
    'api_access': 'advanced',
    'multi_location': 'custom',
}
TIER_ORDER = ['free', 'basic', 'standard', 'advanced', 'custom']

PLANS = [
    ('trial',    'Free trial', None, None, 15,   None, 'advanced', False, 0),
    ('free',     'Free',       0,    0,    1,    50,   'free',     True,  1),
    ('basic',    'Basic',      99,   990,  2,    200,  'basic',    True,  2),
    ('standard', 'Standard',   199,  1990, 5,    1000, 'standard', True,  3),
    ('advanced', 'Advanced',   349,  3490, 15,   None, 'advanced', True,  4),
    ('custom',   'Custom',     None, None, None, None, 'custom',   True,  5),
]


def _features_for(tier):
    reachable = set(TIER_ORDER[:TIER_ORDER.index(tier) + 1])
    return sorted(code for code, first in FEATURES.items() if first in reachable)


def upgrade():
    op.create_table(
        'plan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('price_monthly_ghs', sa.Numeric(10, 2), nullable=True),
        sa.Column('price_annual_ghs', sa.Numeric(10, 2), nullable=True),
        sa.Column('max_users', sa.Integer(), nullable=True),
        sa.Column('max_products', sa.Integer(), nullable=True),
        sa.Column('features_json', sa.Text(), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )

    op.create_table(
        'subscription',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='trialing'),
        sa.Column('trial_ends_at', sa.DateTime(), nullable=True),
        sa.Column('paid_through', sa.DateTime(), nullable=True),
        sa.Column('billing_cycle', sa.String(length=10), nullable=True, server_default='monthly'),
        sa.Column('auto_renew', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('provider', sa.String(length=30), nullable=True),
        sa.Column('provider_customer_ref', sa.String(length=120), nullable=True),
        sa.Column('provider_authorization_code', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['business.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plan.id']),
        sa.PrimaryKeyConstraint('id'),
        # One subscription per business - two would make "what may they do"
        # ambiguous, which is exactly the question this table answers.
        sa.UniqueConstraint('business_id'),
    )

    op.create_table(
        'payment_transaction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('provider_ref', sa.String(length=120), nullable=False),
        sa.Column('amount_ghs', sa.Numeric(10, 2), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('raw_payload_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['business.id']),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscription.id']),
        sa.PrimaryKeyConstraint('id'),
        # The provider's reference is the idempotency key: a webhook that fires
        # twice must not extend a subscription twice.
        sa.UniqueConstraint('provider_ref'),
    )
    op.create_index('ix_payment_transaction_business', 'payment_transaction', ['business_id'])

    plan_table = sa.table(
        'plan',
        sa.column('code', sa.String), sa.column('name', sa.String),
        sa.column('price_monthly_ghs', sa.Numeric), sa.column('price_annual_ghs', sa.Numeric),
        sa.column('max_users', sa.Integer), sa.column('max_products', sa.Integer),
        sa.column('features_json', sa.Text), sa.column('is_public', sa.Boolean),
        sa.column('sort_order', sa.Integer),
    )
    op.bulk_insert(plan_table, [
        {
            'code': code, 'name': name,
            'price_monthly_ghs': monthly, 'price_annual_ghs': annual,
            'max_users': max_users, 'max_products': max_products,
            'features_json': json.dumps(_features_for(tier)),
            'is_public': public, 'sort_order': order,
        }
        for code, name, monthly, annual, max_users, max_products, tier, public, order in PLANS
    ])

    # Every existing business starts on Advanced with no expiry: they were using
    # the product before plans existed, and silently downgrading them would be
    # taking away something they already had.
    op.execute("""
        INSERT INTO subscription (business_id, plan_id, status, billing_cycle,
                                  auto_renew, created_at, updated_at)
        SELECT b.id, (SELECT id FROM plan WHERE code = 'advanced'), 'active', 'monthly',
               false, NOW(), NOW()
        FROM business b
        WHERE NOT EXISTS (SELECT 1 FROM subscription s WHERE s.business_id = b.id)
    """)


def downgrade():
    op.drop_index('ix_payment_transaction_business', table_name='payment_transaction')
    op.drop_table('payment_transaction')
    op.drop_table('subscription')
    op.drop_table('plan')
