"""Tenant isolation and uniqueness — F-17.

Catalogue values are unique per business; user identity is global. Object lookups
use filter_by(id=..., business_id=...).first_or_404(), so tampering with an id in
a URL returns 404 rather than another tenant's record.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from auth.models import Business, User
from extensions import db
from products.models import Brand, Category, ItemGroup, Product, Supplier
from sales.models import Customer


@pytest.fixture
def two_businesses(register, app):
    _a, business_a = register(name='Alpha Shop', email='a@x.example.com')
    _b, business_b = register(name='Beta Shop', email='b@x.example.com', c=app.test_client())
    return business_a, business_b


# ------------------------------------------------------------- global identity

def test_email_is_globally_unique(register, app):
    register(name='Alpha Shop', email='shared@x.example.com')
    response = register(name='Beta Shop', email='shared@x.example.com', c=app.test_client())[0]

    assert User.query.filter_by(email='shared@x.example.com').count() == 1
    assert Business.query.filter_by(name='Beta Shop').first() is None


def test_staff_cannot_reuse_an_email_from_another_business(two_businesses, app):
    _business_a, _business_b = two_businesses
    owner_a = app.test_client()
    owner_a.post('/auth/login', data={'email': 'a@x.example.com', 'password': 'Str0ngPass!23'},
                 follow_redirects=True)

    response = owner_a.post('/auth/users/add', data={
        'name': 'Clash', 'email': 'b@x.example.com', 'password': 'Str0ngPass!23', 'role_id': '2',
    }, follow_redirects=True)

    assert 'already has a TrackTrack account' in response.get_data(as_text=True)
    assert User.query.filter_by(email='b@x.example.com').count() == 1


# --------------------------------------------------------- per-tenant catalogue

@pytest.mark.parametrize('model,field,value', [
    (Category, 'name', 'Beverages'),
    (Supplier, 'name', 'Melcom'),
])
def test_catalogue_names_may_repeat_across_tenants(two_businesses, model, field, value):
    business_a, business_b = two_businesses
    for business_id in (business_a, business_b):
        db.session.add(model(business_id=business_id, **{field: value}))
    db.session.commit()

    assert model.query.filter_by(**{field: value}).count() == 2


def test_sku_may_repeat_across_tenants(two_businesses, make_product):
    business_a, business_b = two_businesses
    make_product(business_a, sku='BW-750')
    make_product(business_b, sku='BW-750')

    assert Product.query.filter_by(sku='BW-750').count() == 2


@pytest.mark.parametrize('model', [Category, Supplier, Brand, ItemGroup])
def test_duplicates_within_one_tenant_are_rejected(two_businesses, model):
    business_a, _business_b = two_businesses
    db.session.add(model(business_id=business_a, name='Duplicate'))
    db.session.commit()

    db.session.add(model(business_id=business_a, name='Duplicate'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


# --------------------------------------------------------------- read isolation

def test_url_tampering_returns_404_not_another_tenants_record(two_businesses, make_product, app):
    business_a, business_b = two_businesses
    foreign = make_product(business_b, sku='BETA-1')

    owner_a = app.test_client()
    owner_a.post('/auth/login', data={'email': 'a@x.example.com', 'password': 'Str0ngPass!23'},
                 follow_redirects=True)

    assert owner_a.get(f'/products/edit/{foreign.id}').status_code == 404


def test_lists_only_show_the_callers_own_records(two_businesses, make_product, app):
    business_a, business_b = two_businesses
    make_product(business_a, sku='ALPHA-1', name='Alpha Water')
    make_product(business_b, sku='BETA-1', name='Beta Water')

    owner_a = app.test_client()
    owner_a.post('/auth/login', data={'email': 'a@x.example.com', 'password': 'Str0ngPass!23'},
                 follow_redirects=True)

    body = owner_a.get('/products/').get_data(as_text=True)
    assert 'Alpha Water' in body
    assert 'Beta Water' not in body


def test_customers_are_isolated(two_businesses, app):
    business_a, business_b = two_businesses
    db.session.add(Customer(business_id=business_a, name='Alpha Customer'))
    db.session.add(Customer(business_id=business_b, name='Beta Customer'))
    db.session.commit()

    owner_a = app.test_client()
    owner_a.post('/auth/login', data={'email': 'a@x.example.com', 'password': 'Str0ngPass!23'},
                 follow_redirects=True)

    body = owner_a.get('/sales/customers').get_data(as_text=True)
    assert 'Alpha Customer' in body
    assert 'Beta Customer' not in body
