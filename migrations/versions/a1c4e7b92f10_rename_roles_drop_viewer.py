"""rename roles to roadmap vocabulary and drop Viewer

Three different role vocabularies existed across the codebase (F-09):
the seed migration created Admin/Manager/Sales Rep/Inventory Clerk/Viewer,
the roadmap specified Owner/Manager/Inventory Staff/Sales Staff/Viewer, and
auth/cli.py looked up a role named 'Owner' that never existed - so
`flask create-owner` could never provision the first account.

This settles on the roadmap vocabulary minus Viewer, which was dropped by
decision D4: authorization becomes per-user (IAM-style) rather than a fixed
read-only tier, and a 2-5 person wholesale business has no real use for it.

Revision ID: a1c4e7b92f10
Revises: 745af8c96a3c
Create Date: 2026-07-31

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a1c4e7b92f10'
down_revision = '745af8c96a3c'
branch_labels = None
depends_on = None


RENAMES = [
    ('Admin', 'Owner'),
    ('Sales Rep', 'Sales Staff'),
    ('Inventory Clerk', 'Inventory Staff'),
]


def upgrade():
    # Rename in place so existing users keep their role_id and permissions.
    # Guard against the target name already existing to keep this re-runnable.
    for old, new in RENAMES:
        op.execute(
            f"UPDATE role SET name = '{new}' "
            f"WHERE name = '{old}' AND NOT EXISTS (SELECT 1 FROM role WHERE name = '{new}')"
        )

    # Anyone sitting on Viewer moves to Sales Staff - the narrowest role that
    # still allows day-to-day work. Never leave role_id NULL: the sidebar and
    # permission checks both read through it.
    op.execute("""
        UPDATE "user" SET role_id = (SELECT id FROM role WHERE name = 'Sales Staff')
        WHERE role_id = (SELECT id FROM role WHERE name = 'Viewer')
    """)
    op.execute("DELETE FROM role_permission WHERE role_id = (SELECT id FROM role WHERE name = 'Viewer')")
    op.execute("DELETE FROM role WHERE name = 'Viewer'")


def downgrade():
    op.execute("INSERT INTO role (name, is_system_role) VALUES ('Viewer', true) ON CONFLICT DO NOTHING")
    op.execute("""
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Viewer' AND p.code IN ('sales.view', 'inventory.view', 'reports.view')
        ON CONFLICT DO NOTHING
    """)
    for old, new in RENAMES:
        op.execute(
            f"UPDATE role SET name = '{old}' "
            f"WHERE name = '{new}' AND NOT EXISTS (SELECT 1 FROM role WHERE name = '{old}')"
        )
