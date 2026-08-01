"""baseline: original pre-Milestone-3 schema

The migration chain had no baseline (F-02). Its first revision,
f977a05df08d, has down_revision = None yet calls batch_alter_table on
category, customer, product, purchase, sale and supplier - tables no earlier
revision creates. So `flask db upgrade` against an empty database failed
immediately, and build.sh worked around it by calling db.create_all(), which
never runs migrations and therefore never seeded roles or permissions. Neither
path could stand up a working database.

This revision creates the schema exactly as it stood at commit c26a12d, giving
the existing chain something real to diff against. It is deliberately a
faithful snapshot of that original schema, not the current models - every later
revision builds on top of it.

Revision ID: 0000_baseline
Revises:
Create Date: 2026-07-31

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0000_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # An already-populated database (one previously built by db.create_all())
    # keeps its tables; this revision is then just a chain anchor to stamp.
    if 'product' in existing:
        return

    op.create_table(
        'category',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'supplier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('contact', sa.String(length=100), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=100), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'customer',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=100), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'product',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('sku', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('unit_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('quantity_in_stock', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('min_stock_alert', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['category.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sku'),
    )
    op.create_table(
        'sale',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sale_date', sa.Date(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'sale_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sale_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('price_at_sale', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id']),
        sa.ForeignKeyConstraint(['sale_id'], ['sale.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'purchase',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('purchase_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('purchase_date', sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id']),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    for table in ('purchase', 'sale_item', 'sale', 'product', 'customer', 'supplier', 'category'):
        op.drop_table(table)
