"""sale lines remember which unit they were sold in

Revision ID: d7e93b04c815
Revises: c4d81f96a2e7
Create Date: 2026-08-17

`quantity` stays in base units and `price_at_sale` stays per base unit, so the
four places that sum `price_at_sale * quantity` - services/credit.py:47,
credit/models.py:71 and reports/routes.py:94,100 - keep working untouched, and
so does every stock query. Selling two cartons of 24 stores 48 and the price of
one bottle.

What is added is only what is needed to say it back: `sell_unit` and
`sold_quantity`. The invoice then reads "2 cartons" rather than "48 bottles",
which is what the customer was actually charged for.

Both are frozen history, for the same reason `list_price` is. A product's pack
size can be edited afterwards, and deriving `48 / factor` at read time would
silently rewrite an old sale the day someone corrects a carton from 24 to 12.

**The widening is a money fix, not tidiness.** `price_at_sale` per base unit is
derived by dividing a pack price, and at two decimals a carton at 1,000 for 24
stores 41.67 a bottle, so 48 bottles bill 2,000.16 against the 2,000.00 agreed.
Six decimals is the same reasoning that widened PurchaseOrderItem.unit_cost in
F-41, now applied on the side the customer actually pays. Widening is
loss-free; every existing row keeps its exact value.
"""
import sqlalchemy as sa
from alembic import op

revision = 'd7e93b04c815'
down_revision = 'c4d81f96a2e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sale_item', sa.Column(
        'sell_unit', sa.String(length=10), nullable=False,
        server_default=sa.text("'base'")))
    # Null means "the same as quantity", which is what every existing row means.
    op.add_column('sale_item', sa.Column('sold_quantity', sa.Integer(), nullable=True))

    op.alter_column('sale_item', 'price_at_sale',
                    existing_type=sa.Numeric(10, 2), type_=sa.Numeric(14, 6),
                    existing_nullable=False)
    op.alter_column('sale_item', 'list_price',
                    existing_type=sa.Numeric(10, 2), type_=sa.Numeric(14, 6),
                    existing_nullable=True)

    op.create_check_constraint(
        'ck_sale_item_sell_unit', 'sale_item',
        "sell_unit IN ('base', 'purchase')")


def downgrade():
    op.drop_constraint('ck_sale_item_sell_unit', 'sale_item', type_='check')
    op.alter_column('sale_item', 'list_price',
                    existing_type=sa.Numeric(14, 6), type_=sa.Numeric(10, 2),
                    existing_nullable=True)
    op.alter_column('sale_item', 'price_at_sale',
                    existing_type=sa.Numeric(14, 6), type_=sa.Numeric(10, 2),
                    existing_nullable=False)
    op.drop_column('sale_item', 'sold_quantity')
    op.drop_column('sale_item', 'sell_unit')
