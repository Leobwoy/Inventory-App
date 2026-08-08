"""a login for whoever runs TrackTrack, separate from any business

Confirming a payment decides what a business has paid for, so it cannot be a
permission: a tenant Owner controls every permission inside their own business
and would simply grant it to themselves.

The first attempt put the vendor inside a tenant - a login belongs to a
business, so running TrackTrack meant registering a business you do not own.
That is muddled, and it was noticed. The person who runs the platform is not a
customer of it, so they get their own table, their own login and their own
session key. A tenant session can never become a platform session, because
nothing reads across.

Bootstrapped with `flask create-platform-admin`; there is no signup page, on
purpose.

Revision ID: b7e13d804f52
Revises: a2f47b91c6e3
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7e13d804f52'
down_revision = 'a2f47b91c6e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'platform_admin',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_platform_admin_email'),
    )


def downgrade():
    op.drop_table('platform_admin')
