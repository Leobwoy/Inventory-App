"""per-business discount ceiling

price_at_sale was written straight from submitted form data (F-07). The field is
readonly in the template, but that is a rendering hint - the value still posts,
so a modified request could carry any number including zero or below cost, and
nothing in any report would show it.

Server-side price resolution needs a policy to enforce. max_discount_percent is
the ceiling on how far below list a sale may go, for staff holding
sales.discount. Default 0: no discounting until an Owner deliberately allows it.

Revision ID: f2c95a71b6de
Revises: e6b73f8c04d1
Create Date: 2026-08-01

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'f2c95a71b6de'
down_revision = 'e6b73f8c04d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('business', sa.Column('max_discount_percent', sa.Numeric(5, 2),
                                        nullable=False, server_default='0'))
    op.execute("INSERT INTO permission (code, description) "
               "VALUES ('sales.discount', 'Sell below the listed price') "
               "ON CONFLICT (code) DO NOTHING")


def downgrade():
    op.drop_column('business', 'max_discount_percent')
