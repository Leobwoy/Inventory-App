"""Authorization — F-05, F-16.

RBAC was modelled and seeded but enforced on 2 of 55 routes, so any staff
account was effectively an admin account. These tests exercise direct URL
access, which is the thing that actually failed: hiding a nav link protects
nothing.
"""
import pytest

from auth.models import User
from auth.permissions import ALL, PRESETS
from products.models import Product


@pytest.fixture
def business(register):
    _client, business_id = register()
    return business_id


def test_owner_holds_every_permission(business):
    owner = User.query.filter_by(business_id=business, role_id=1).first() \
        or User.query.filter_by(business_id=business).first()
    assert all(owner.can(code) for code in ALL)


@pytest.mark.parametrize('role_name', ['Manager', 'Inventory Staff', 'Sales Staff'])
def test_preset_matches_its_definition(business, make_staff, role_name):
    make_staff(business, role_name, f'{role_name.replace(" ", "").lower()}@x.example.com')
    user = User.query.filter_by(name=role_name).one()
    assert user.permission_codes() == PRESETS[role_name]


@pytest.mark.parametrize('role_name', ['Inventory Staff', 'Sales Staff'])
def test_floor_staff_cannot_see_cost_price(business, make_staff, role_name):
    """A real business requirement, not UI polish (F-16)."""
    make_staff(business, role_name, f'{role_name.replace(" ", "").lower()}@x.example.com')
    assert not User.query.filter_by(name=role_name).one().can('products.cost_price.view')


@pytest.mark.parametrize('path', [
    '/purchases/', '/purchases/add', '/products/suppliers',
    '/products/brands', '/products/categories', '/auth/users', '/backup_restore',
])
def test_sales_staff_blocked_by_url(business, make_staff, path):
    client = make_staff(business, 'Sales Staff', 'sales@x.example.com')
    assert client.get(path).status_code == 403


@pytest.mark.parametrize('path', ['/sales/', '/sales/add', '/sales/customers',
                                  '/products/', '/reports/sales'])
def test_sales_staff_allowed_where_expected(business, make_staff, path):
    client = make_staff(business, 'Sales Staff', 'sales@x.example.com')
    assert client.get(path).status_code == 200


@pytest.mark.parametrize('path', ['/sales/', '/sales/customers', '/auth/users', '/backup_restore'])
def test_inventory_staff_blocked_by_url(business, make_staff, path):
    client = make_staff(business, 'Inventory Staff', 'inv@x.example.com')
    assert client.get(path).status_code == 403


def test_write_operations_are_blocked_not_only_reads(business, make_staff, make_product):
    product = make_product(business)
    client = make_staff(business, 'Sales Staff', 'sales@x.example.com')

    assert client.post(f'/products/delete/{product.id}').status_code == 403
    assert Product.query.get(product.id) is not None


def test_bulk_delete_is_checked_per_action(business, make_staff, make_product):
    """One endpoint, several privilege levels - the check lives in the view."""
    product = make_product(business)
    client = make_staff(business, 'Sales Staff', 'sales@x.example.com')

    response = client.post('/products/bulk_action',
                           data={'action': 'delete', 'product_ids': [str(product.id)]},
                           follow_redirects=True)
    assert 'do not have permission' in response.get_data(as_text=True)
    assert Product.query.get(product.id) is not None


def test_export_is_gated_separately_from_view(business, make_staff):
    client = make_staff(business, 'Sales Staff', 'sales@x.example.com')
    assert client.get('/reports/sales').status_code == 200
    response = client.get('/reports/sales?export=csv', follow_redirects=True)
    assert 'permission to export' in response.get_data(as_text=True)


def test_nav_reflects_permissions(business, make_staff):
    client = make_staff(business, 'Sales Staff', 'sales@x.example.com')
    body = client.get('/').get_data(as_text=True)
    assert 'nav-sales' in body
    assert 'nav-purchases' not in body
    assert 'nav-users' not in body


def test_owner_can_retune_an_individual(business, make_staff, register, app):
    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    make_staff(business, 'Sales Staff', 'sales@x.example.com')
    user_id = User.query.filter_by(email='sales@x.example.com').one().id

    owner.post(f'/auth/users/{user_id}/permissions',
               data={'permissions': ['sales.view', 'purchase_orders.view']},
               follow_redirects=True)

    user = User.query.get(user_id)
    assert user.permission_codes() == {'sales.view', 'purchase_orders.view'}


def test_unknown_permission_codes_are_ignored(business, make_staff, app):
    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    make_staff(business, 'Sales Staff', 'sales@x.example.com')
    user_id = User.query.filter_by(email='sales@x.example.com').one().id

    owner.post(f'/auth/users/{user_id}/permissions',
               data={'permissions': ['sales.view', 'not.a.real.permission']},
               follow_redirects=True)

    codes = User.query.get(user_id).permission_codes()
    assert 'not.a.real.permission' not in codes
    assert 'sales.view' in codes


def test_owner_cannot_be_restricted_or_suspended(business, app):
    owner_client = app.test_client()
    owner_client.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
                      follow_redirects=True)
    owner_id = User.query.filter_by(email='owner@ab.example.com').one().id

    response = owner_client.get(f'/auth/users/{owner_id}/permissions', follow_redirects=True)
    assert 'cannot be restricted' in response.get_data(as_text=True)

    owner_client.post(f'/auth/users/{owner_id}/toggle_active', follow_redirects=True)
    assert User.query.get(owner_id).is_active


def test_suspension_takes_effect_on_an_active_session(business, make_staff, app):
    from extensions import db
    staff_client = make_staff(business, 'Manager', 'mgr@x.example.com')
    assert staff_client.get('/products/').status_code == 200

    User.query.filter_by(email='mgr@x.example.com').one().is_active = False
    db.session.commit()

    assert staff_client.get('/products/').status_code in (302, 403)


def test_cost_price_field_is_absent_for_unpermitted_staff(business, make_staff):
    """Hidden in the template is not enough - the bound field is removed."""
    inventory = make_staff(business, 'Inventory Staff', 'inv@x.example.com')
    assert 'cost_price' not in inventory.get('/products/add').get_data(as_text=True)

    manager = make_staff(business, 'Manager', 'mgr2@x.example.com')
    assert 'cost_price' in manager.get('/products/add').get_data(as_text=True)


def test_posted_cost_price_is_ignored_on_edit(business, make_staff, make_product):
    """A hand-crafted POST must not reach the column."""
    product = make_product(business, cost_price='2.00')
    inventory = make_staff(business, 'Inventory Staff', 'inv@x.example.com')

    inventory.post(f'/products/edit/{product.id}', data={
        'name': 'Renamed', 'unit_price': '3.50', 'cost_price': '999',
        'brand_id': str(product.brand_id), 'item_group_id': str(product.item_group_id),
        'category_id': '0', 'sku': product.sku, 'base_uom': 'pcs', 'purchase_uom': 'pcs',
        'units_per_purchase_uom': '1', 'min_stock_alert': '0', 'quantity_in_stock': '0',
    }, follow_redirects=True)

    refreshed = Product.query.get(product.id)
    assert float(refreshed.cost_price) == 2.00     # unchanged
    assert refreshed.name == 'Renamed'             # the rest of the edit applied


def test_export_omits_cost_price_for_unpermitted_staff(business, make_staff, make_product):
    product = make_product(business)
    sku = product.sku
    inventory = make_staff(
        business, 'Inventory Staff', 'inv@x.example.com',
        permissions={'products.view', 'reports.export'},
    )
    body = inventory.post('/products/bulk_action',
                          data={'action': 'export_csv', 'product_ids': [str(product.id)]}
                          ).get_data(as_text=True)
    assert 'Cost Price' not in body
    assert sku in body

    manager = make_staff(business, 'Manager', 'mgr2@x.example.com')
    manager_body = manager.post('/products/bulk_action',
                                data={'action': 'export_csv', 'product_ids': [str(product.id)]}
                                ).get_data(as_text=True)
    assert 'Cost Price' in manager_body
