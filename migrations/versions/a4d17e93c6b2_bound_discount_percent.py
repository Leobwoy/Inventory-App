"""bound max_discount_percent to 0-100

Nothing stopped the column holding, say, 150. services/pricing.py computes the
floor as list * (100 - ceiling) / 100, which then goes negative, and the
"is the request below the floor" test passes for every positive price - quietly
disabling the discount ceiling it exists to enforce.

Enforced in the database so no future settings screen can bypass it.

Revision ID: a4d17e93c6b2
Revises: f2c95a71b6de
Create Date: 2026-08-02

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a4d17e93c6b2'
down_revision = 'f2c95a71b6de'
branch_labels = None
depends_on = None


def upgrade():
    # Clamp anything already out of range before the constraint lands.
    op.execute('UPDATE business SET max_discount_percent = 0 WHERE max_discount_percent < 0')
    op.execute('UPDATE business SET max_discount_percent = 100 WHERE max_discount_percent > 100')
    op.create_check_constraint(
        'ck_business_max_discount_percent_range',
        'business',
        'max_discount_percent >= 0 AND max_discount_percent <= 100',
    )


def downgrade():
    op.drop_constraint('ck_business_max_discount_percent_range', 'business', type_='check')
