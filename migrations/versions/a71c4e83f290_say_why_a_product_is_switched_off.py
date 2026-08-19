"""say why a product is switched off

Revision ID: a71c4e83f290
Revises: f3a91d70c2b5
Create Date: 2026-08-19

A product the owner retired and one a downgrade switched off were
indistinguishable: both were `is_active = false`. That is fine while nothing
says anything about them, and wrong the moment the catalogue starts telling
people *why* - "locked by your plan, upgrade to unlock" printed over a line
somebody deliberately stopped stocking is a lie, in the one place the app is
asking them for money.

False for every existing row, which is right: nothing has ever been switched off
by a plan before, because until now nothing enforced a cap on what already
existed.
"""
import sqlalchemy as sa
from alembic import op

revision = 'a71c4e83f290'
down_revision = 'f3a91d70c2b5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product', sa.Column(
        'locked_by_plan', sa.Boolean(), nullable=False,
        server_default=sa.text('false')))


def downgrade():
    op.drop_column('product', 'locked_by_plan')
