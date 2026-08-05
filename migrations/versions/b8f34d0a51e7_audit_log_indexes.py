"""index the audit log for the filters the view offers

The activity page filters by business, person, action and date range, and orders
by timestamp descending. Without indexes every one of those is a sequential scan
over a table that only ever grows - and it grows fastest for the busiest
customers, who are the ones who most need to search it.

Revision ID: b8f34d0a51e7
Revises: a4d17e93c6b2
Create Date: 2026-08-03

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b8f34d0a51e7'
down_revision = 'a4d17e93c6b2'
branch_labels = None
depends_on = None


def upgrade():
    # Covers the default view (a business's entries, newest first) and the
    # date-range filter, which both lead with business_id then timestamp.
    op.create_index('ix_audit_log_business_timestamp', 'audit_log',
                    ['business_id', 'timestamp'])
    op.create_index('ix_audit_log_business_action', 'audit_log',
                    ['business_id', 'action'])
    op.create_index('ix_audit_log_user', 'audit_log', ['user_id'])


def downgrade():
    op.drop_index('ix_audit_log_user', table_name='audit_log')
    op.drop_index('ix_audit_log_business_action', table_name='audit_log')
    op.drop_index('ix_audit_log_business_timestamp', table_name='audit_log')
