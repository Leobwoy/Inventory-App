"""The permission catalogue and the role presets built from it.

Permissions are the authorization vocabulary; roles are only presets that seed a
user's initial set. Authorization always reads UserPermission, never Role, so
this module is the single place the vocabulary is defined - the seeding
migration and the user-management UI both build from it.
"""

# code -> (description, UI group). Group drives the checkbox grid layout.
PERMISSIONS = {
    'products.view':            ('View products and stock levels', 'Products'),
    'products.create':          ('Add new products', 'Products'),
    'products.edit':            ('Edit existing products', 'Products'),
    'products.delete':          ('Delete products', 'Products'),
    'products.cost_price.view': ('See cost prices and margins', 'Products'),
    'catalogue.manage':         ('Manage categories, brands and item groups', 'Products'),

    'suppliers.view':           ('View suppliers', 'Purchasing'),
    'suppliers.manage':         ('Add, edit and delete suppliers', 'Purchasing'),
    'purchase_orders.view':     ('View purchase orders', 'Purchasing'),
    'purchase_orders.create':   ('Create purchase orders', 'Purchasing'),
    'purchase_orders.approve':  ('Approve purchase orders', 'Purchasing'),
    'purchase_orders.receive':  ('Receive goods against a purchase order', 'Purchasing'),

    'sales.view':               ('View sales and invoices', 'Sales'),
    'sales.create':             ('Record sales', 'Sales'),
    'sales.void':               ('Void or delete sales', 'Sales'),
    'sales.discount':           ('Sell below the listed price', 'Sales'),
    'customers.view':           ('View customers', 'Sales'),
    'customers.manage':         ('Add, edit and delete customers', 'Sales'),

    'credit.view':              ('View customer balances and ageing', 'Credit'),
    'credit.record_payment':    ('Record payments against balances', 'Credit'),

    'reports.view':             ('View reports', 'Reports'),
    'reports.export':           ('Export reports to PDF, Excel and CSV', 'Reports'),

    'users.manage':             ('Add staff and set their permissions', 'Administration'),
    'settings.manage':          ('Change business settings and branding', 'Administration'),
    'backup.run':               ("Export and restore this business's data", 'Administration'),
    'audit.view':               ('View the audit log', 'Administration'),
}

# Order the groups appear in the permission grid.
GROUP_ORDER = ['Products', 'Purchasing', 'Sales', 'Credit', 'Reports', 'Administration']

# Legacy coarse codes from the original seed migration. Kept so nothing breaks
# mid-migration, but no longer granted to anyone.
DEPRECATED = {'inventory.manage', 'inventory.view'}

ALL = set(PERMISSIONS)

# Role presets. Owner is special-cased in User.can() and always holds everything,
# so it is intentionally absent here.
PRESETS = {
    'Manager': ALL - {'users.manage', 'settings.manage', 'backup.run'},

    'Inventory Staff': {
        'products.view', 'products.create', 'products.edit', 'catalogue.manage',
        'suppliers.view', 'suppliers.manage',
        'purchase_orders.view', 'purchase_orders.create', 'purchase_orders.receive',
        'reports.view',
    },

    'Sales Staff': {
        'products.view',
        'sales.view', 'sales.create',
        'customers.view', 'customers.manage',
        'credit.view', 'credit.record_payment',
        'reports.view',
    },
}


def preset_for(role_name):
    """Permission codes a new user starts with for `role_name`."""
    if role_name == 'Owner':
        return set(ALL)
    return set(PRESETS.get(role_name, set()))
