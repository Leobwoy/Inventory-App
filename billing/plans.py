"""The plan catalogue and the feature vocabulary it hands out.

Two independent gates run in this application and must not be confused:

    permission  - may this *person* do it        (auth/permissions.py)
    feature     - has this *business* paid for it (here)

A Sales Staff member on an Advanced plan cannot manage users, because they lack
the permission. An Owner on the Free plan cannot open the credit ledger, because
the business has not paid for it. Both checks apply; neither implies the other.
"""

# code -> (description, the plan it first appears on). Descriptions are shown on
# the upgrade prompt, so they are written for a business owner, not a developer.
FEATURES = {
    'purchase_orders':     ('Purchase orders and goods receipt', 'basic'),
    'exports.csv':         ('Export lists to CSV', 'basic'),
    'exports.all':         ('Export to Excel and PDF', 'standard'),
    'credit_ledger':       ('Track what customers owe you', 'standard'),
    'uom_conversion':      ('Buy in cartons, sell in pieces', 'standard'),
    'expiry_alerts':       ('Batch and expiry tracking with alerts', 'standard'),
    'offline':             ('Keep selling when the network drops', 'standard'),
    'notifications':       ('Alerts inbox for low stock and reorders', 'standard'),
    'supplier_scorecards': ('Supplier reliability scoring', 'advanced'),
    'price_comparison':    ('Compare supplier prices for a product', 'advanced'),
    'margin_reports':      ('Profit and margin reporting', 'advanced'),
    'audit_log':           ('Activity log of who changed what', 'advanced'),
    'api_access':          ('API access', 'advanced'),
    'multi_location':      ('Multiple warehouses with stock transfer', 'custom'),
}

# Cheapest first. Each tier includes everything below it.
TIER_ORDER = ['free', 'basic', 'standard', 'advanced', 'custom']


def features_for_tier(tier):
    """Every feature code available at `tier`, including inherited ones."""
    if tier not in TIER_ORDER:
        return set()
    reachable = set(TIER_ORDER[:TIER_ORDER.index(tier) + 1])
    return {code for code, (_desc, first_tier) in FEATURES.items() if first_tier in reachable}


# Prices in GHS, anchored to the observed Ghanaian SME software band of 99-250
# for POS/inventory tools. Annual is ten months for twelve - priced generously on
# purpose, because mobile money cannot auto-renew and every annual sale removes
# eleven chances for a manual renewal to be forgotten.
# Display names use the ladder a Ghanaian trader already recognises, so a
# customer can place themselves on it without reading the feature list. `code` is
# what the application keys off everywhere; the name is presentation only, and
# changing it again later touches no logic.
PLANS = [
    # code, name, monthly, annual, max_users, max_products, tier, public, order
    ('trial',    'Full Access Trial', 0,   0,    15,   None, 'advanced', False, 0),
    ('free',     'Kiosk',             0,   0,    1,    50,   'free',     True,  1),
    ('basic',    'Shop',              99,  990,  2,    200,  'basic',    True,  2),
    ('standard', 'Depot',             199, 1990, 5,    1000, 'standard', True,  3),
    ('advanced', 'Distributor',       349, 3490, 15,   None, 'advanced', True,  4),
    ('custom',   'Enterprise',        None, None, None, None, 'custom',  True,  5),
]

TRIAL_DAYS = 14
GRACE_DAYS = 7          # after paid_through lapses, before downgrading to free
