"""make Product.is_active NOT NULL

is_active was nullable with only a Python-side default, so a row inserted by SQL
or by an older code path could hold NULL - a third state meaning neither active
nor retired.

That ambiguity was harmless while nothing read the column. It stops being
harmless now that plan limits count *active* products: a NULL row would be
neither counted nor blocked, which is exactly the gap someone gaming the free
tier would find.

Revision ID: e1b7c93f2a68
Revises: d9c48b2e0f31
Create Date: 2026-08-03

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e1b7c93f2a68'
down_revision = 'd9c48b2e0f31'
branch_labels = None
depends_on = None


def upgrade():
    # Existing NULLs are products created before the column was read; they were
    # all sellable, so they are active.
    op.execute('UPDATE product SET is_active = true WHERE is_active IS NULL')
    op.alter_column('product', 'is_active',
                    existing_type=sa.Boolean(),
                    nullable=False,
                    server_default=sa.true())


def downgrade():
    op.alter_column('product', 'is_active',
                    existing_type=sa.Boolean(),
                    nullable=True,
                    server_default=None)
