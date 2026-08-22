"""a message from the platform to one business

Revision ID: c5b820f4ae13
Revises: a71c4e83f290
Create Date: 2026-08-19

Approving or rejecting a payment in the console changed the business's plan and
told the business nothing. It landed in the activity log, which answers "what
happened to this account" months later and is no help at all to somebody who
opens the app on Monday wondering why their plan changed over the weekend.

Deliberately not an alert. `services/notifications.py` is derived and its inbox
is a paid feature; this is a stored message about a decision a person made, and
it reaches every business on every plan - "your payment was rejected" is not
something anybody should have to buy a plan to be told.
"""
import sqlalchemy as sa
from alembic import op

revision = 'c5b820f4ae13'
down_revision = 'a71c4e83f290'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'business_notice',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('business_id', sa.Integer(), sa.ForeignKey('business.id'), nullable=False),
        sa.Column('level', sa.String(length=20), nullable=False, server_default='info'),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('body', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        # Null until the owner closes it, so the platform can tell a message
        # that was read from one that was never delivered.
        sa.Column('seen_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_business_notice_business_id', 'business_notice', ['business_id'])


def downgrade():
    op.drop_index('ix_business_notice_business_id', table_name='business_notice')
    op.drop_table('business_notice')
