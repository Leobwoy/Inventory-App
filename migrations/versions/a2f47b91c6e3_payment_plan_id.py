"""record which plan a payment was for

confirm() recovered the plan by matching the recorded amount against today's
prices. That works until a price changes, which it will: a payment claimed at
GHS 199 and confirmed after Depot moves to GHS 249 finds no plan at all, and a
customer who has paid gets an error instead of the thing they paid for. Worse,
if two plans ever share a price it silently picks whichever came back first.

The plan is a fact about the transaction, so it is stored on the transaction.
amount_ghs, period_start and period_end stay - they are what was actually
charged and for how long, which must not move when a price list does.

Nullable because rows predating this column exist; confirm() falls back to the
old price lookup for those alone.

Revision ID: a2f47b91c6e3
Revises: f6c81d42a973
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2f47b91c6e3'
down_revision = 'f6c81d42a973'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('payment_transaction', sa.Column('plan_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_payment_transaction_plan', 'payment_transaction',
                          'plan', ['plan_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_payment_transaction_plan', 'payment_transaction', type_='foreignkey')
    op.drop_column('payment_transaction', 'plan_id')
