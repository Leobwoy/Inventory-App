"""per-tenant uniqueness constraints

Product.sku, Category.name, Supplier.name and User.email were UNIQUE across the
whole table rather than per business (F-17). The first tenant to create SKU
"BW-750", a category called "Beverages" or a supplier named "Melcom"
permanently blocked every other tenant from using that value, surfacing as an
error message that made no sense to them - and getting sharply worse with each
new customer.

Tenants are fully isolated, so all four become composite constraints on
(business_id, ...). User.email included: the same person may legitimately hold
accounts at two different businesses. Login resolves this by verifying the
password against every candidate and, only on success, offering a business
picker - see auth/routes.py.

Brand.name and ItemGroup.name had no uniqueness at all, letting a business
create two brands called "BelAqua". Added, scoped per business.

Revision ID: b3e8d4f16a27
Revises: c7f21a3d8e45
Create Date: 2026-08-01

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b3e8d4f16a27'
down_revision = 'c7f21a3d8e45'
branch_labels = None
depends_on = None


# (table, old global constraint, new constraint, columns)
SWAPS = [
    ('product',    'product_sku_key',     'uq_product_business_sku',      ['business_id', 'sku']),
    ('category',   'category_name_key',   'uq_category_business_name',    ['business_id', 'name']),
    ('supplier',   'supplier_name_key',   'uq_supplier_business_name',    ['business_id', 'name']),
    ('user',       'user_email_key',      'uq_user_business_email',       ['business_id', 'email']),
]

ADDITIONS = [
    ('brand',      'uq_brand_business_name',      ['business_id', 'name']),
    ('item_group', 'uq_item_group_business_name', ['business_id', 'name']),
]


def upgrade():
    for table, old_name, new_name, columns in SWAPS:
        # IF EXISTS: a database built by the old db.create_all() path may have
        # auto-generated a differently named constraint.
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS {old_name}')
        op.create_unique_constraint(new_name, table, columns)

    for table, name, columns in ADDITIONS:
        op.create_unique_constraint(name, table, columns)


def downgrade():
    for table, name, _columns in ADDITIONS:
        op.drop_constraint(name, table, type_='unique')

    for table, old_name, new_name, _columns in SWAPS:
        op.drop_constraint(new_name, table, type_='unique')
        # Restoring a global constraint can fail if rows now collide across
        # tenants - which is exactly the situation this migration exists to allow.
        column = 'sku' if table == 'product' else ('email' if table == 'user' else 'name')
        op.create_unique_constraint(old_name, table, [column])
