"""remember which theme each person chose

The app is used on phones in warehouse doorways and open markets in full sun,
where a dark screen is genuinely hard to read - and until now dark was the only
option. This is the storage behind the switch.

Per user, not per business, and not in localStorage. localStorage answers "has
this browser been set", and the question is "what does this person prefer": a
wholesaler signing in on the shop tablet and again on their own phone should not
have to set it twice, and clearing a browser should not undo the answer. Per
business would be worse still - the owner at a desk and the clerk in the doorway
want opposite things, and only one of them can have it.

Three values, and 'system' is the default rather than 'dark':

  system  follow the device, resolved in the browser before first paint
  light
  dark

'system' has to exist as a distinct value from 'dark'. Storing the *resolved*
theme would freeze whatever the device happened to say on the day they signed
up, and never follow it again.

NOT NULL with a server default, so every existing row gets 'system' and no code
anywhere has to treat null as a fourth case.

Revision ID: e2c93f5a71b8
Revises: d1b58e0472a9
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2c93f5a71b8'
down_revision = 'd1b58e0472a9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('theme_pref', sa.String(length=8),
                                    nullable=False, server_default='system'))


def downgrade():
    op.drop_column('user', 'theme_pref')
