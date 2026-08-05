"""give the plans market-appropriate display names

"Free / Basic / Standard / Advanced" says nothing about who each tier is for, and
reads like every other SaaS pricing page. These names use the ladder a Ghanaian
trader already recognises - kiosk, shop, depot, distributor - so a customer can
place themselves on it without reading the feature list.

Display only. The `code` column is what the application keys off
(billing/plans.py, services/limits.py, @requires_feature), and it is unchanged,
so renaming a tier again later is one row per plan and touches no logic.

Revision ID: d9c48b2e0f31
Revises: c2a67f81d940
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd9c48b2e0f31'
down_revision = 'c2a67f81d940'
branch_labels = None
depends_on = None


NAMES = {
    'trial': 'Full Access Trial',
    'free': 'Kiosk',
    'basic': 'Shop',
    'standard': 'Depot',
    'advanced': 'Distributor',
    'custom': 'Enterprise',
}

PREVIOUS = {
    'trial': 'Free trial',
    'free': 'Free',
    'basic': 'Basic',
    'standard': 'Standard',
    'advanced': 'Advanced',
    'custom': 'Custom',
}


def _rename(mapping):
    for code, name in mapping.items():
        op.execute(
            sa.text('UPDATE plan SET name = :name WHERE code = :code')
            .bindparams(name=name, code=code)
        )


def upgrade():
    _rename(NAMES)


def downgrade():
    _rename(PREVIOUS)
