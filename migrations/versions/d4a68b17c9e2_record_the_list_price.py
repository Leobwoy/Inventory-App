"""record the list price a sale line was discounted from

A discount was enforced and audited but never stored on the sale itself, so
nothing downstream could tell a discounted line from a normal one. The invoice,
the sales list and the reports all showed only what was charged.

It cannot be recomputed later either: product prices change, so comparing an old
sale against today's list price would invent discounts that never happened and
hide ones that did. The price at the time has to be kept with the line.

Nullable because every existing row predates it - a null means "not known",
which is different from "no discount".

Revision ID: d4a68b17c9e2
Revises: c3f57a26b0d8
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4a68b17c9e2'
down_revision = 'c3f57a26b0d8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sale_item', sa.Column('list_price', sa.Numeric(10, 2), nullable=True))


def downgrade():
    op.drop_column('sale_item', 'list_price')
