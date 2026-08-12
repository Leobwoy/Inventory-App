"""record when a user has finished or dismissed the guided tour

Kept on the user rather than in localStorage, because localStorage answers "has
this browser seen it" and the question is "has this person seen it". A wholesaler
who signs in on the shop tablet and again on their own phone should not be walked
through the app twice, and clearing a browser should not undo the answer.

Nullable, and null means "not yet". Existing users are therefore offered the tour
once - which is right: it did not exist when they registered, so none of them
have been shown it.

Both endings write a timestamp. Someone who closed the tour on the second step
has told us something, and asking again tomorrow ignores the answer; the reason
is kept in the audit trail rather than here, because the only question this
column has to answer is whether to start.

Revision ID: d1b58e0472a9
Revises: c9a41f76b3e8
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1b58e0472a9'
down_revision = 'c9a41f76b3e8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('tour_seen_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('user', 'tour_seen_at')
