"""per-user permissions (IAM) and the full permission catalogue

RBAC was modelled and seeded but enforced on 2 of 55 routes, so any staff
account was effectively an admin account (F-05). The seeded vocabulary was also
too coarse - seven codes with no way to express PO approval, cost-price
visibility, export rights or backup access.

This creates user_permission as the single source of truth for authorization.
Role becomes a preset: choosing one at user creation copies its permissions in,
after which the Owner edits them per person. Nothing reads Role to authorize, so
there are no precedence rules to reason about.

The preset contents are inlined below rather than imported from
auth/permissions.py on purpose: a migration must be an immutable snapshot of
intent at this point in history, not something that silently changes behaviour
when the application's presets are later edited.

Revision ID: e6b73f8c04d1
Revises: d5a91c62e7b8
Create Date: 2026-08-01

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e6b73f8c04d1'
down_revision = 'd5a91c62e7b8'
branch_labels = None
depends_on = None


PERMISSIONS = [
    ('products.view', 'View products and stock levels'),
    ('products.create', 'Add new products'),
    ('products.edit', 'Edit existing products'),
    ('products.delete', 'Delete products'),
    ('products.cost_price.view', 'See cost prices and margins'),
    ('catalogue.manage', 'Manage categories, brands and item groups'),
    ('suppliers.view', 'View suppliers'),
    ('suppliers.manage', 'Add, edit and delete suppliers'),
    ('purchase_orders.view', 'View purchase orders'),
    ('purchase_orders.create', 'Create purchase orders'),
    ('purchase_orders.approve', 'Approve purchase orders'),
    ('purchase_orders.receive', 'Receive goods against a purchase order'),
    ('sales.view', 'View sales and invoices'),
    ('sales.create', 'Record sales'),
    ('sales.void', 'Void or delete sales'),
    ('sales.discount', 'Sell below the listed price'),
    ('customers.view', 'View customers'),
    ('customers.manage', 'Add, edit and delete customers'),
    ('credit.view', 'View customer balances and ageing'),
    ('credit.record_payment', 'Record payments against balances'),
    ('reports.view', 'View reports'),
    ('reports.export', 'Export reports to PDF, Excel and CSV'),
    ('users.manage', 'Add staff and set their permissions'),
    ('settings.manage', 'Change business settings and branding'),
    ('backup.run', "Export and restore this business's data"),
    ('audit.view', 'View the audit log'),
]

ALL_CODES = {code for code, _ in PERMISSIONS}

MANAGER = sorted(ALL_CODES - {'users.manage', 'settings.manage', 'backup.run'})

INVENTORY_STAFF = [
    'products.view', 'products.create', 'products.edit', 'catalogue.manage',
    'suppliers.view', 'suppliers.manage',
    'purchase_orders.view', 'purchase_orders.create', 'purchase_orders.receive',
    'reports.view',
]

SALES_STAFF = [
    'products.view',
    'sales.view', 'sales.create',
    'customers.view', 'customers.manage',
    'credit.view', 'credit.record_payment',
    'reports.view',
]

# Owner is special-cased in User.can() and always holds everything, but the rows
# are still written so the permission grid renders correctly for an Owner.
PRESETS = {
    'Owner': sorted(ALL_CODES),
    'Manager': MANAGER,
    'Inventory Staff': INVENTORY_STAFF,
    'Sales Staff': SALES_STAFF,
}


def upgrade():
    op.create_table(
        'user_permission',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.Column('granted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permission.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'permission_id'),
    )

    for code, description in PERMISSIONS:
        op.execute(sa.text(
            'INSERT INTO permission (code, description) VALUES (:code, :description) '
            'ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description'
        ).bindparams(code=code, description=description))

    # Backfill: every existing user receives their role's preset.
    for role_name, codes in PRESETS.items():
        op.execute(sa.text("""
            INSERT INTO user_permission (user_id, permission_id, granted_at)
            SELECT u.id, p.id, NOW()
            FROM "user" u
            JOIN role r ON r.id = u.role_id
            JOIN permission p ON p.code = ANY(:codes)
            WHERE r.name = :role_name
            ON CONFLICT DO NOTHING
        """).bindparams(codes=list(codes), role_name=role_name))

    # The old coarse codes are superseded. Detach them from every role so nothing
    # grants them; the rows stay for reference.
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE code IN ('inventory.manage', 'inventory.view'))"
    )


def downgrade():
    op.drop_table('user_permission')
    op.execute(
        "DELETE FROM permission WHERE code IN ("
        + ', '.join(f"'{code}'" for code, _ in PERMISSIONS if code
                    not in ('users.manage', 'settings.manage', 'sales.create',
                            'sales.view', 'reports.view', 'backup.run'))
        + ')'
    )
