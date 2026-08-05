"""keep the business logo in the database

logo_path assumed a persistent filesystem. There is not one: Koyeb rebuilds the
container on every deploy, so a logo written to disk survives until the next
release and then silently disappears from every invoice. There is no object
store either, and adding one to carry a single image the size of an email
signature is not worth the dependency.

The bytes go in the row. Logos are small, they are read once per page at most,
and this way branding survives a redeploy.

logo_path is dropped rather than kept: nothing ever wrote to it.

Revision ID: b8e4f02d691c
Revises: a7d3e91c58b4
"""
from alembic import op
import sqlalchemy as sa

revision = 'b8e4f02d691c'
down_revision = 'a7d3e91c58b4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('business', sa.Column('logo_data', sa.LargeBinary(), nullable=True))
    op.add_column('business', sa.Column('logo_mimetype', sa.String(length=50), nullable=True))
    op.drop_column('business', 'logo_path')


def downgrade():
    op.add_column('business', sa.Column('logo_path', sa.String(length=255), nullable=True))
    op.drop_column('business', 'logo_mimetype')
    op.drop_column('business', 'logo_data')
