"""store a walk-in's phone number on the sale

A walk-in who buys on credit has to be reachable. The name alone identifies the
debt on a list but does not help anyone collect it, and there is no customer
record to hold a number.

Revision ID: c3f57a26b0d8
Revises: b8e4f02d691c
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3f57a26b0d8'
down_revision = 'b8e4f02d691c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sale', sa.Column('customer_phone', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('sale', 'customer_phone')
