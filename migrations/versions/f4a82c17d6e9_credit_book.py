"""credit book: payments against sales

Ghanaian wholesale runs on trade credit, and the application recorded every sale
as though it were settled. This adds the payment side, so a balance can be
derived from sales minus payments.

Bookkeeping only - no payment gateway. A row here means someone received money
and wrote it down. `reference` holds the mobile money transaction ID the customer
forwards, which is how this market reconciles.

Revision ID: f4a82c17d6e9
Revises: e1b7c93f2a68
Create Date: 2026-08-03

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f4a82c17d6e9'
down_revision = 'e1b7c93f2a68'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('sale_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False, server_default='cash'),
        sa.Column('reference', sa.String(length=120), nullable=True),
        sa.Column('paid_on', sa.Date(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('recorded_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['business.id']),
        # Deleting a voided sale takes its payments with it; the sale.void audit
        # entry keeps the record of what was there.
        sa.ForeignKeyConstraint(['sale_id'], ['sale.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['recorded_by'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('amount > 0', name='ck_payment_amount_positive'),
    )
    # Balances are derived on every read, so the columns those queries group by
    # need to be indexed from the start rather than after the first slow report.
    op.create_index('ix_payment_sale', 'payment', ['sale_id'])
    op.create_index('ix_payment_business_customer', 'payment', ['business_id', 'customer_id'])
    op.create_index('ix_payment_business_paid_on', 'payment', ['business_id', 'paid_on'])


def downgrade():
    op.drop_index('ix_payment_business_paid_on', table_name='payment')
    op.drop_index('ix_payment_business_customer', table_name='payment')
    op.drop_index('ix_payment_sale', table_name='payment')
    op.drop_table('payment')
