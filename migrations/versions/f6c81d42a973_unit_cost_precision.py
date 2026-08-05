"""keep enough precision in a converted per-unit cost (F-41)

PurchaseOrderItem.unit_cost stores the base-unit cost, derived by dividing a
purchase-unit price by the pack factor. At two decimal places that division
loses money whenever the price does not divide evenly, and the loss multiplies
by every unit on the line:

    GHS 1.00 a carton of 24  ->  0.04 a unit  ->  100 cartons record 96.00
    GHS 55.00 a carton of 12 ->  4.58 a unit  ->   40 cartons record 2198.40

The cedis are small. The consequence is not: this figure is the cost price
behind every margin, and it is what services/sourcing.py compares one supplier
against another with - the feature whose entire job is saying who is genuinely
cheaper per unit.

Six decimal places makes the residue invisible at any realistic order size
(1.00/24 stored as 0.041667 recovers 1.000008 across a carton). Money is still
presented at two; only the stored intermediate gets the room it needed.

Existing rows are widened in place - the values are already rounded, so nothing
can be recovered for them, but nothing is lost either.

Revision ID: f6c81d42a973
Revises: e5b92c73f1a4
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6c81d42a973'
down_revision = 'e5b92c73f1a4'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('purchase_order_item', 'unit_cost',
                    existing_type=sa.Numeric(10, 2),
                    type_=sa.Numeric(14, 6),
                    existing_nullable=True)


def downgrade():
    # Narrowing rounds every stored value back to pesewas.
    op.alter_column('purchase_order_item', 'unit_cost',
                    existing_type=sa.Numeric(14, 6),
                    type_=sa.Numeric(10, 2),
                    existing_nullable=True)
