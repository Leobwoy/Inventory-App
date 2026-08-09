"""let each item group say whether expiry matters to it

D1: the target customer is beverage and FMCG wholesale, where most stock does
not meaningfully expire. Warning about every carton of mineral water sixty days
out trains people to ignore the warnings, and then the one that mattered - the
yoghurt, the juice - goes unread with the rest.

So expiry alerting is opt-in per item group. Batches still record expiry dates
and FEFO still draws from the earliest regardless; this only decides what is
worth interrupting someone about.

Defaults to false. Nothing alerted on expiry before this migration, so no
business loses a warning it was relying on.

Revision ID: c9a41f76b3e8
Revises: b7e13d804f52
"""
from alembic import op
import sqlalchemy as sa

revision = 'c9a41f76b3e8'
down_revision = 'b7e13d804f52'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('item_group',
                  sa.Column('track_expiry', sa.Boolean(), nullable=False,
                            server_default=sa.false()))


def downgrade():
    op.drop_column('item_group', 'track_expiry')
