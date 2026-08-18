"""the carton is what you type

Revision ID: e8f2a19c3d64
Revises: d7e93b04c815
Create Date: 2026-08-18

The pack price stopped being an optional extra and became the price. A
wholesaler buys by the carton, sells by the carton and quotes by the carton;
what one bottle works out at is arithmetic they never do, and it is not a
number they would agree on anyway - the same bottle goes for 3.00 in one shop
and 3.50 in the next.

`unit_price` and `cost_price` stay stored and stay NOT NULL. They stop being
*typed*: the form asks for the carton and the route divides. Keeping them is
what keeps this change small - making them nullable would push a NULL into
price sorting, where it orders unpredictably on Postgres, into the offline
catalogue payload, and into every report that multiplies by them.

**The backfill invents nothing.** `pack_price IS NULL` already means "a pack is
count x the single price" - `services/uom.price_for` has always read it that
way. Writing that product out is the same number the app was already quoting,
just no longer implied. Products with no real pack are left alone: there is
nothing to multiply and no carton to price.

**The widening is a round-trip fix.** `cost_price` is now derived by dividing a
typed carton cost, and at two decimals a carton at 1,000 for 24 stores 41.67 a
bottle. The edit form multiplies back to fill the box, so it would read 1,000.08
- and every open-and-save would nudge it again. Six decimals is the same
reasoning as F-41 and d7e93b04c815, and widening is loss-free.

`unit_price` deliberately stays at two decimals. It is a real per-bottle selling
price, charged in whole pesewas, and it is re-derived from the stored pack price
on every save rather than round-tripped through the form - so it cannot drift.
"""
import sqlalchemy as sa
from alembic import op

revision = 'e8f2a19c3d64'
down_revision = 'd7e93b04c815'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('product', 'cost_price',
                    existing_type=sa.Numeric(10, 2), type_=sa.Numeric(14, 6),
                    existing_nullable=False)

    # The same three conditions services/uom.has_conversion applies, so this
    # touches exactly the rows the app already treats as having a pack.
    op.execute("""
        UPDATE product
           SET pack_price = unit_price * units_per_purchase_uom
         WHERE pack_price IS NULL
           AND units_per_purchase_uom > 1
           AND lower(trim(purchase_uom)) <> lower(trim(base_uom))
    """)


def downgrade():
    # The backfilled prices are left in place. Null and "count x the single
    # price" mean the same thing to every reader, so clearing them would be
    # indistinguishable from data loss for any price genuinely typed since.
    op.alter_column('product', 'cost_price',
                    existing_type=sa.Numeric(14, 6), type_=sa.Numeric(10, 2),
                    existing_nullable=False)
