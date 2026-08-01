"""seed_roles_and_permissions

Revision ID: 745af8c96a3c
Revises: 485dd2872397
Create Date: 2026-07-10 14:53:52.725875

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '745af8c96a3c'
down_revision = '485dd2872397'
branch_labels = None
depends_on = None


def upgrade():
    # Define roles
    op.execute("INSERT INTO role (name, is_system_role) VALUES ('Admin', true) ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role (name, is_system_role) VALUES ('Manager', true) ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role (name, is_system_role) VALUES ('Sales Rep', true) ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role (name, is_system_role) VALUES ('Inventory Clerk', true) ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO role (name, is_system_role) VALUES ('Viewer', true) ON CONFLICT DO NOTHING")
    
    # Define permissions
    permissions = [
        ('users.manage', 'Manage users and roles'),
        ('settings.manage', 'Manage business settings'),
        ('sales.create', 'Create and edit sales'),
        ('sales.view', 'View sales records'),
        ('inventory.manage', 'Create POs and receive goods'),
        ('inventory.view', 'View stock levels'),
        ('reports.view', 'View financial reports')
    ]
    for code, desc in permissions:
        op.execute(f"INSERT INTO permission (code, description) VALUES ('{code}', '{desc}') ON CONFLICT DO NOTHING")
        
    # Map Admin to all permissions
    op.execute('''
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Admin'
        ON CONFLICT DO NOTHING
    ''')
    
    # Map Manager (no user/settings manage)
    op.execute('''
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Manager' AND p.code NOT IN ('users.manage', 'settings.manage')
        ON CONFLICT DO NOTHING
    ''')
    
    # Map Sales Rep
    op.execute('''
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Sales Rep' AND p.code IN ('sales.create', 'sales.view', 'inventory.view', 'reports.view')
        ON CONFLICT DO NOTHING
    ''')
    
    # Map Inventory Clerk
    op.execute('''
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Inventory Clerk' AND p.code IN ('inventory.manage', 'inventory.view')
        ON CONFLICT DO NOTHING
    ''')
    
    # Map Viewer
    op.execute('''
        INSERT INTO role_permission (role_id, permission_id)
        SELECT r.id, p.id FROM role r, permission p
        WHERE r.name = 'Viewer' AND p.code IN ('sales.view', 'inventory.view', 'reports.view')
        ON CONFLICT DO NOTHING
    ''')


def downgrade():
    pass
