"""revert User.email to globally unique

b3e8d4f16a27 scoped User.email per business, on the reasoning that tenants are
fully isolated. That was reconsidered: a per-tenant email means an address no
longer identifies a *person*, and every identity-recovery flow inherits the
ambiguity - password reset, MFA enrolment, security alerts, support lookups.
The login picker solved it once; password reset would have had to solve it
again, and reset cannot use "the password verified" as its disclosure gate.

Worse, per-tenant email makes account takeover structurally possible: with
shared family addresses, generic info@ addresses or an Owner's typo, the same
string can belong to two different humans, so any reset scoped to an email
rather than an account hands one person the other's credentials.

Global email costs one thing: a person genuinely running two businesses needs a
second address. If that case ever becomes real, the answer is a Membership
table (global User identity, many business memberships, business chosen after
authentication) - not per-tenant emails.

The per-tenant constraints on product, category, supplier, brand and item_group
from b3e8d4f16a27 are correct and are left in place.

Revision ID: d5a91c62e7b8
Revises: b3e8d4f16a27
Create Date: 2026-08-01

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd5a91c62e7b8'
down_revision = 'b3e8d4f16a27'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Fail loudly and usefully rather than on a cryptic constraint violation.
    duplicates = bind.execute(sa.text(
        'SELECT lower(email) AS e, count(*) FROM "user" GROUP BY lower(email) HAVING count(*) > 1'
    )).fetchall()
    if duplicates:
        listed = ', '.join(f'{row[0]} ({row[1]} accounts)' for row in duplicates[:10])
        raise RuntimeError(
            'Cannot make User.email globally unique - these addresses are used by more than '
            f'one account: {listed}. Change the duplicate addresses, then re-run this migration.'
        )

    op.drop_constraint('uq_user_business_email', 'user', type_='unique')
    op.create_unique_constraint('user_email_key', 'user', ['email'])


def downgrade():
    op.drop_constraint('user_email_key', 'user', type_='unique')
    op.create_unique_constraint('uq_user_business_email', 'user', ['business_id', 'email'])
