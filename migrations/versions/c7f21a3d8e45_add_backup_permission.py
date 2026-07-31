"""add backup.run permission, Owner only

/backup_restore previously sat behind HTTP Basic auth with a hardcoded username
and a default password, entirely outside the permission system (F-03). This adds
the permission it should have been guarded by from the start.

Owner only: an export contains every price, margin, customer and supplier the
business has, and an import replaces its operational data.

Revision ID: c7f21a3d8e45
Revises: a1c4e7b92f10
Create Date: 2026-07-31

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c7f21a3d8e45'
down_revision = 'a1c4e7b92f10'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO permission (code, description) "
        "VALUES ('backup.run', 'Export and restore this business''s data') "
        "ON CONFLICT DO NOTHING"
    )
    op.execute("""
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Owner' AND p.code = 'backup.run'
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.execute(
        "DELETE FROM role_permission WHERE permission_id = "
        "(SELECT id FROM permission WHERE code = 'backup.run')"
    )
    op.execute("DELETE FROM permission WHERE code = 'backup.run'")
