"""give a sale the id the device generated for it

A sale recorded offline is sent when the signal returns, and "sent" is exactly
where duplicates come from: the request times out after the server committed,
the device retries, and the wholesaler has sold the same crate twice.

The device generates an id before queueing and sends it with the sale. The
server treats that id as the identity of the sale, so a retry finds the row
already there and returns the original rather than writing a second one.

Unique per business, not globally: two devices in two businesses could in
principle produce the same value, and a global constraint would let one
tenant's retry collide with another's sale.

Nullable - a sale recorded in the browser has no device id, and every existing
row predates this.

Revision ID: e5b92c73f1a4
Revises: d4a68b17c9e2
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5b92c73f1a4'
down_revision = 'd4a68b17c9e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sale', sa.Column('client_id', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_sale_business_client_id', 'sale',
                                ['business_id', 'client_id'])
    # The idempotency check runs on every synced sale, so it gets its own index.
    op.create_index('ix_sale_client_id', 'sale', ['client_id'])


def downgrade():
    op.drop_index('ix_sale_client_id', table_name='sale')
    op.drop_constraint('uq_sale_business_client_id', 'sale', type_='unique')
    op.drop_column('sale', 'client_id')
