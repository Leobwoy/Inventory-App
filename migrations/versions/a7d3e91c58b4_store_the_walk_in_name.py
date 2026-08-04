"""store the walk-in customer's name on the sale

A sale to someone not in the customer list captured a name on the form and then
threw it away - it was passed to the invoice as a URL query parameter and never
persisted. Reloading the invoice lost it, and a walk-in who bought on credit
became anonymous the moment the page closed, so there was no way to tell which
of them owed what.

Nullable: a sale to a registered customer takes its name from that record, and
every existing row predates the column.

Revision ID: a7d3e91c58b4
Revises: f4a82c17d6e9
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7d3e91c58b4'
down_revision = 'f4a82c17d6e9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sale', sa.Column('customer_name', sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column('sale', 'customer_name')
