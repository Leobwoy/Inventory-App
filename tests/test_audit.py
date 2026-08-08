"""Audit trail — F-19.

AuditLog was modelled and migrated with no writers at all, so there was no way to
answer "who changed this price" - the question it exists for. These tests pin
down which actions are recorded, that each is attributed to a person and a
business, and that a failed audit write can never roll back the operation it is
describing.
"""
import datetime
import json

import pytest

from auth.models import AuditLog, User
from extensions import db
from products.models import Product
from sales.models import Sale
from services import stock

TODAY = datetime.date.today()
PASSWORD = 'Str0ngPass!23'


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    product = make_product(business_id, unit_price='3.00', cost_price='2.00', stock=100)
    return client, business_id, product


def actions_for(business_id):
    return [e.action for e in AuditLog.query.filter_by(business_id=business_id)]


def details(action):
    entry = AuditLog.query.filter_by(action=action).order_by(AuditLog.id.desc()).first()
    return json.loads(entry.details_json) if entry and entry.details_json else {}


# ------------------------------------------------------------------- catalogue

def test_price_change_records_before_and_after(shop):
    """The headline question: who changed this price, from what, to what."""
    client, business_id, product = shop

    client.post(f'/products/edit/{product.id}', data={
        'name': product.name, 'unit_price': '4.25', 'cost_price': '2.00',
        'brand_id': str(product.brand_id), 'item_group_id': str(product.item_group_id),
        'category_id': '0', 'sku': product.sku, 'base_uom': 'pcs', 'purchase_uom': 'pcs',
        'units_per_purchase_uom': '1', 'min_stock_alert': '0', 'quantity_in_stock': '100',
    }, follow_redirects=True)

    assert 'product.price_change' in actions_for(business_id)
    recorded = details('product.price_change')
    assert recorded['field'] == 'unit_price'
    assert recorded['old'] == '3.00'
    assert recorded['new'] == '4.25'


def test_unchanged_price_is_not_logged(shop):
    """An edit that leaves prices alone must not fill the log with noise."""
    client, business_id, product = shop

    client.post(f'/products/edit/{product.id}', data={
        'name': 'Renamed only', 'unit_price': '3.00', 'cost_price': '2.00',
        'brand_id': str(product.brand_id), 'item_group_id': str(product.item_group_id),
        'category_id': '0', 'sku': product.sku, 'base_uom': 'pcs', 'purchase_uom': 'pcs',
        'units_per_purchase_uom': '1', 'min_stock_alert': '0', 'quantity_in_stock': '100',
    }, follow_redirects=True)

    assert 'product.price_change' not in actions_for(business_id)


def test_product_deletion_is_recorded(register, make_product):
    client, business_id = register()
    product = make_product(business_id, sku='NO-HISTORY')     # never traded
    sku = product.sku

    client.post(f'/products/delete/{product.id}', follow_redirects=True)

    assert 'product.delete' in actions_for(business_id)
    assert details('product.delete')['sku'] == sku


def test_product_with_history_is_kept_not_deleted(shop):
    """Deleting a traded product used to raise a NOT NULL violation - a 500 with
    no explanation - and would have erased the history behind every report."""
    client, business_id, product = shop      # has a stock batch

    response = client.post(f'/products/delete/{product.id}', follow_redirects=True)

    assert response.status_code == 200
    assert 'cannot be deleted' in response.get_data(as_text=True)
    assert Product.query.get(product.id) is not None
    assert 'product.delete' not in actions_for(business_id)


def test_deactivating_retires_a_product_without_losing_history(shop):
    client, business_id, product = shop

    client.post(f'/products/deactivate/{product.id}', follow_redirects=True)

    assert Product.query.get(product.id).is_active is False
    assert 'product.deactivate' in actions_for(business_id)


# ----------------------------------------------------------------- stock moves

def test_goods_receipt_is_recorded(register, make_product, make_po):
    client, business_id = register()
    product = make_product(business_id)
    po, item = make_po(business_id, product, quantity=100)

    client.post(f'/purchases/receive/{po.id}', data={
        'received_date': TODAY.isoformat(), f'qty_{item.id}': '40',
        f'batch_{item.id}': 'LOT-9', f'expiry_{item.id}': '',
    }, follow_redirects=True)

    assert 'purchase_order.receive' in actions_for(business_id)
    recorded = details('purchase_order.receive')
    assert recorded['status'] == 'partially_received'
    assert recorded['lines'][0]['qty'] == 40
    assert recorded['lines'][0]['batch'] == 'LOT-9'


def test_stock_adjustment_is_recorded(shop):
    """A count correction moves stock with no sale or delivery to explain it."""
    _client, business_id, product = shop

    stock.adjust(product, 75, business_id, reason='stock count')
    db.session.commit()

    assert 'stock.adjust' in actions_for(business_id)
    recorded = details('stock.adjust')
    assert recorded['old'] == 100
    assert recorded['new'] == 75
    assert recorded['delta'] == -25
    assert recorded['reason'] == 'stock count'


def test_voiding_a_sale_records_what_it_contained(shop):
    client, business_id, product = shop
    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0', 'customer_name': 'W',
        'items-0-product_id': str(product.id), 'items-0-quantity': '5',
        'items-0-price_at_sale': '3.00',
    }, follow_redirects=True)
    sale_id = Sale.query.one().id

    client.post('/sales/bulk_action', data={'action': 'delete', 'sale_ids': [str(sale_id)]},
                follow_redirects=True)

    assert 'sale.void' in actions_for(business_id)
    recorded = details('sale.void')
    assert recorded['lines'][0]['qty'] == 5
    assert recorded['lines'][0]['sku'] == product.sku


# ------------------------------------------------------------------- the people

def test_staff_creation_and_permission_changes_are_recorded(shop, app):
    client, business_id, _product = shop

    client.post('/auth/users/add', data={
        'name': 'Efua', 'email': 'efua@x.example.com', 'password': PASSWORD, 'role_id': '4',
    }, follow_redirects=True)
    assert 'user.create' in actions_for(business_id)

    staff_id = User.query.filter_by(email='efua@x.example.com').one().id
    client.post(f'/auth/users/{staff_id}/permissions',
                data={'permissions': ['sales.view']}, follow_redirects=True)

    assert 'user.permissions_change' in actions_for(business_id)
    recorded = details('user.permissions_change')
    assert 'sales.view' not in recorded['revoked']
    assert recorded['revoked']            # the rest of the preset was taken away


def test_suspension_is_recorded(shop):
    client, business_id, _product = shop
    client.post('/auth/users/add', data={
        'name': 'Efua', 'email': 'efua@x.example.com', 'password': PASSWORD, 'role_id': '4',
    }, follow_redirects=True)
    staff_id = User.query.filter_by(email='efua@x.example.com').one().id

    client.post(f'/auth/users/{staff_id}/toggle_active', follow_redirects=True)
    assert 'user.suspend' in actions_for(business_id)

    client.post(f'/auth/users/{staff_id}/toggle_active', follow_redirects=True)
    assert 'user.reinstate' in actions_for(business_id)


def test_backup_export_is_recorded(shop):
    client, business_id, _product = shop
    client.post('/backup_restore', data={'backup': '1'})
    assert 'backup.export' in actions_for(business_id)


# ------------------------------------------------------------------ properties

def test_every_entry_is_attributed(register, make_product):
    client, business_id = register()
    product = make_product(business_id, sku='NO-HISTORY')
    client.post(f'/products/delete/{product.id}', follow_redirects=True)

    entries = AuditLog.query.filter_by(business_id=business_id).all()
    assert entries
    assert all(e.user_id is not None for e in entries)
    assert all(e.business_id == business_id for e in entries)
    assert all(e.timestamp is not None for e in entries)


def test_entries_are_scoped_per_business(register, make_product, app):
    """One tenant must never see another's activity."""
    client_a, business_a = register(name='Alpha', email='a@x.example.com')
    _client_b, business_b = register(name='Beta', email='b@x.example.com')
    product_a = make_product(business_a)

    client_a.post(f'/products/delete/{product_a.id}', follow_redirects=True)

    assert AuditLog.query.filter_by(business_id=business_a).count() >= 1
    assert AuditLog.query.filter_by(business_id=business_b).count() == 0


def test_a_failing_audit_write_never_breaks_the_operation(register, make_product, monkeypatch):
    """A lost log line is bad; a lost sale is worse."""
    client, business_id = register()
    product = make_product(business_id, sku='NO-HISTORY')
    product_id = product.id          # read before the row goes away
    monkeypatch.setattr('services.audit.AuditLog',
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError('boom')))

    response = client.post(f'/products/delete/{product_id}', follow_redirects=True)

    assert response.status_code == 200
    assert Product.query.get(product_id) is None      # the delete still happened


# ------------------------------------------------------------------- the screen

def test_page_is_gated_and_filters(register, make_product, make_staff):
    client, business_id = register()
    product = make_product(business_id, sku='NO-HISTORY')
    client.post(f'/products/delete/{product.id}', follow_redirects=True)

    assert client.get('/auth/audit').status_code == 200
    body = client.get('/auth/audit').get_data(as_text=True)
    assert 'product.delete' in body

    # Filtering to an action with no entries must empty the table. Checking the
    # whole page for the action name would match the filter dropdown, which lists
    # every action regardless of what is selected.
    filtered = client.get('/auth/audit?action=stock.adjust').get_data(as_text=True)
    assert 'Nothing recorded yet' in filtered

    staff = make_staff(business_id, 'Sales Staff', 'sales@x.example.com')
    assert staff.get('/auth/audit').status_code == 403


def test_a_bad_date_filter_does_not_take_the_page_down(register):
    """start_date and end_date were compared straight against a timestamp
    column. On PostgreSQL an unparseable value raises DataError and returns 500,
    which anyone holding audit.view could trigger from the URL bar. SQLite would
    have compared it lexically and shown nothing."""
    client, _business_id = register()

    for bad in ('abc', '2026-13-45', "'; DROP TABLE audit_log; --", '2026/08/05'):
        response = client.get(f'/auth/audit?start_date={bad}&end_date={bad}')
        assert response.status_code == 200, f'{bad!r} broke the audit log'


def test_the_date_filter_still_filters(register, app):
    """The parsing must not quietly turn every filter into a no-op."""
    import datetime
    from auth.models import AuditLog
    from extensions import db

    client, business_id = register()
    old = AuditLog(business_id=business_id, action='sale.create',
                   timestamp=datetime.datetime(2020, 1, 1, 12, 0))
    recent = AuditLog(business_id=business_id, action='sale.void',
                      timestamp=datetime.datetime.utcnow())
    db.session.add_all([old, recent])
    db.session.commit()

    body = client.get('/auth/audit?start_date=2019-01-01&end_date=2020-12-31').get_data(as_text=True)
    # Only the results table. Both actions also appear in the filter dropdown,
    # so searching the whole page would pass no matter what the filter did.
    results = body.split('<tbody>', 1)[1].split('</tbody>', 1)[0]
    assert 'sale.create' in results
    assert 'sale.void' not in results


def test_an_explicit_none_user_is_not_replaced_by_the_signed_in_one(register):
    """`user_id=None` means "nobody in this business did this" - a platform
    admin confirming a payment, or a scheduled job. It used to be
    indistinguishable from "not supplied", so such an action performed while a
    tenant session happened to exist would have been signed with that tenant's
    user, crediting a customer with a decision they did not make."""
    from auth.models import AuditLog
    from extensions import db
    from services import audit

    client, business_id = register()
    # Inside a request, so current_user is a real signed-in tenant.
    with client.application.test_request_context():
        from flask_login import login_user
        from auth.models import User
        login_user(User.query.filter_by(business_id=business_id).first())

        audit.log('test.platform_action', business_id=business_id, user_id=None)
        audit.log('test.tenant_action', business_id=business_id)
        db.session.commit()

    platform_entry = AuditLog.query.filter_by(action='test.platform_action').one()
    tenant_entry = AuditLog.query.filter_by(action='test.tenant_action').one()

    assert platform_entry.user_id is None, 'an explicit None was overwritten'
    assert tenant_entry.user_id is not None, 'omitting it should still infer the user'
