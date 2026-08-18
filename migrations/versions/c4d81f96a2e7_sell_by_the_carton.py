"""sell by the carton: a pack price and a default selling unit

Revision ID: c4d81f96a2e7
Revises: e2c93f5a71b8
Create Date: 2026-08-17

A wholesaler sells by the crate, and a crate is cheaper per bottle than the same
bottles bought singly - that gap is the whole reason a shop buys a case. It
cannot be derived from the single price, so it has to be stored.

`pack_price` is nullable on purpose. Null means "a carton is simply count x
unit_price", which is true for every product that exists today and keeps this
migration a pure addition: nothing is backfilled, nothing changes price.

`sell_unit` defaults to 'base' for the same reason. Every existing product sells
in pieces today because that is the only thing the app could do, so 'base' is
not a guess - it is what those rows already mean.

The CHECK on units_per_purchase_uom is overdue rather than new. `uom.factor()`
has always clamped a 0 or negative to 1 at read time, which masks a bad row
instead of preventing it; the form asks for min=1 but with Optional(), and the
route writes `... or 1`. Existing rows are repaired before the constraint lands,
because a constraint that cannot be applied to live data is a failed deploy.
"""
import sqlalchemy as sa
from alembic import op

revision = 'c4d81f96a2e7'
down_revision = 'e2c93f5a71b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product', sa.Column('pack_price', sa.Numeric(10, 2), nullable=True))
    op.add_column('product', sa.Column(
        'sell_unit', sa.String(length=10), nullable=False,
        server_default=sa.text("'base'")))

    # Repair before constraining. factor() has been hiding these at read time.
    op.execute('UPDATE product SET units_per_purchase_uom = 1 '
               'WHERE units_per_purchase_uom IS NULL OR units_per_purchase_uom < 1')
    op.create_check_constraint(
        'ck_product_units_per_purchase_uom_positive', 'product',
        'units_per_purchase_uom >= 1')
    op.create_check_constraint(
        'ck_product_sell_unit', 'product',
        "sell_unit IN ('base', 'purchase', 'both')")


def downgrade():
    op.drop_constraint('ck_product_sell_unit', 'product', type_='check')
    op.drop_constraint('ck_product_units_per_purchase_uom_positive', 'product',
                       type_='check')
    op.drop_column('product', 'sell_unit')
    op.drop_column('product', 'pack_price')
