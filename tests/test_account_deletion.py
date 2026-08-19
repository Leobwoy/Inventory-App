"""Closing a business account.

The only irreversible action in the application. Everything here is about the
two ways it can be wrong: deleting when it should not have, and leaving
something behind when it should not have.

Invariant 10 is not in tension with this. It says customer data is never deleted
*to enforce a plan limit* - a downgrade removes access, not records, because the
business did not ask for that. This is the business asking, about its own data.
The rule protects owners from us, not owners from themselves.
"""
import pytest

from auth.models import AuditLog, Business, User
from billing.models import Subscription
from extensions import db
from products.models import Product, Supplier
from sales.models import Customer, Sale


@pytest.fixture
def shop(register, make_product, make_staff):
    client, business_id = register()
    make_product(business_id, sku='P-1', name='Club Beer 330ml', stock=48)
    make_staff(business_id, 'Manager', 'mgr@x.example.com')
    make_staff(business_id, 'Sales Staff', 'clerk@x.example.com')
    db.session.add(Customer(business_id=business_id, name='Adjei Enterprise'))
    db.session.add(Supplier(business_id=business_id, name='Accra Brewery PLC'))
    db.session.commit()
    return client, business_id


def business_name(business_id):
    return Business.query.get(business_id).name


def delete(client, business_id, name=None, password='Str0ngPass!23'):
    return client.post('/auth/account', data={
        'confirm_name': business_name(business_id) if name is None else name,
        'password': password,
    }, follow_redirects=True)


# --- it refuses, loudly, unless everything lines up --------------------------

def test_a_wrong_name_deletes_nothing(shop):
    client, business_id = shop

    page = delete(client, business_id, name='Some Other Shop').get_data(as_text=True)

    assert 'nothing was deleted' in page
    assert Business.query.get(business_id) is not None
    assert Product.query.filter_by(business_id=business_id).count() == 1


def test_a_wrong_password_deletes_nothing(shop):
    client, business_id = shop

    page = delete(client, business_id, password='not-my-password').get_data(as_text=True)

    assert 'nothing was deleted' in page
    assert Business.query.get(business_id) is not None


def test_a_manager_with_settings_permission_cannot_close_the_account(shop, make_staff):
    """`settings.manage` is how a business lets somebody keep the address and
    the discount ceiling up to date. Closing the account is not that, so the
    route checks `is_owner` on top of the permission."""
    _client, business_id = shop
    manager = make_staff(business_id, 'Manager', 'boss@x.example.com',
                         permissions={'settings.manage'})

    page = manager.post('/auth/account', data={
        'confirm_name': business_name(business_id), 'password': 'Str0ngPass!23',
    }, follow_redirects=True).get_data(as_text=True)

    assert 'Only the Owner' in page
    assert Business.query.get(business_id) is not None


# --- and when it does go, nothing is left ------------------------------------

def test_everything_belonging_to_the_business_is_gone(shop):
    client, business_id = shop

    delete(client, business_id)

    assert Business.query.get(business_id) is None
    assert User.query.filter_by(business_id=business_id).count() == 0
    assert Product.query.filter_by(business_id=business_id).count() == 0
    assert Customer.query.filter_by(business_id=business_id).count() == 0
    assert Supplier.query.filter_by(business_id=business_id).count() == 0
    assert Sale.query.filter_by(business_id=business_id).count() == 0
    assert Subscription.query.filter_by(business_id=business_id).count() == 0
    assert AuditLog.query.filter_by(business_id=business_id).count() == 0


def test_every_staff_login_goes_with_it(shop):
    """Not just the owner. A staff account left behind is a login against a
    business that no longer exists."""
    client, business_id = shop
    emails = {u.email for u in User.query.filter_by(business_id=business_id)}
    assert len(emails) == 3

    delete(client, business_id)

    assert User.query.filter(User.email.in_(emails)).count() == 0


def test_another_business_is_untouched(shop, register, make_product):
    """The whole application is one database with a business_id on every row.
    A delete that reached past its own tenant is the worst bug this codebase
    could have."""
    client, business_id = shop
    _other_client, other_id = register(name='Beta Traders', email='b@x.example.com')
    make_product(other_id, sku='B-1', name='Beta Water')

    delete(client, business_id)

    assert Business.query.get(other_id) is not None
    assert Product.query.filter_by(business_id=other_id).count() == 1
    assert User.query.filter_by(business_id=other_id).count() == 1


def test_the_owner_is_signed_out(shop):
    """The session points at a user row that no longer exists.

    What actually carries this is the deletion: Flask-Login's user loader
    returns None for the missing row, so the session reads as anonymous whether
    or not `logout_user()` ran. Falsification confirmed it - removing that call
    leaves this green. It stays because clearing the cookie deliberately beats
    relying on a lookup failing, and this test is honest about which of the two
    it is measuring.
    """
    client, business_id = shop

    page = delete(client, business_id).get_data(as_text=True)

    assert 'has been deleted' in page
    assert client.get('/products/', follow_redirects=True).status_code == 200
    assert 'Sign in' in client.get('/products/', follow_redirects=True).get_data(as_text=True)


# --- what the page says before you do it -------------------------------------

def test_the_page_counts_what_would_be_destroyed(shop):
    """"Delete my account" and "delete my account, which is 1 product, 3 staff
    and 1 customer" are different sentences, and only the second gets read."""
    client, business_id = shop

    page = client.get('/auth/account').get_data(as_text=True)

    assert 'Close this account' in page
    assert business_name(business_id) in page
    assert 'cannot be undone' in page
    assert 'backup' in page.lower(), 'no way out is offered'


def test_the_settings_tabs_reach_every_section(shop):
    client, _business_id = shop

    page = client.get('/auth/account').get_data(as_text=True)

    for label in ('Business', 'Users', 'Activity log', 'Subscription', 'Backup', 'Account'):
        assert label in page
