"""tighten the product caps

Revision ID: f3a91d70c2b5
Revises: e8f2a19c3d64
Create Date: 2026-08-19

Set at the user's direction: Kiosk 20, Shop 70, Depot 200, Distributor 500,
Enterprise unlimited. Every one of these is a reduction, and Distributor gains a
ceiling where it had none.

`billing/plans.py` is not read at runtime - it seeded this table once and every
limit the application enforces is read from the row. So the constant and the
column both have to move, and this is the half that has any effect.

**The trial moves with Distributor**, from unlimited to 500. It is not in the
list the user gave, but it grants the advanced tier and already mirrored
advanced on seats. Leaving it unlimited would let somebody build a catalogue of
600 during a fortnight's trial and lose a hundred products the day it ended -
the trial should preview the plan it is a trial of.

Nothing is deactivated here. A business that is over a new cap is brought into
line by `services/limits.enforce_plan_limits`, which runs on the next plan
change and on the daily check - so it happens in application code, with an audit
entry, rather than silently inside a schema migration where nobody would ever
find it.
"""
import sqlalchemy as sa
from alembic import op

revision = 'f3a91d70c2b5'
down_revision = 'e8f2a19c3d64'
branch_labels = None
depends_on = None

#: code -> new max_products. None means unlimited.
CAPS = {'trial': 500, 'free': 20, 'basic': 70, 'standard': 200,
        'advanced': 500, 'custom': None}
WAS = {'trial': None, 'free': 50, 'basic': 200, 'standard': 1000,
       'advanced': None, 'custom': None}


def _apply(caps):
    plan = sa.table('plan', sa.column('code', sa.String),
                    sa.column('max_products', sa.Integer))
    for code, cap in caps.items():
        op.execute(plan.update().where(plan.c.code == op.inline_literal(code))
                   .values(max_products=cap))


def upgrade():
    _apply(CAPS)


def downgrade():
    _apply(WAS)
