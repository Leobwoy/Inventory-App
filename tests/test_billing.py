"""Plan limits and feature gating — B4 (Stage 1.9).

Scaffolding only: no payment provider is involved. What these pin down is that
plan limits and feature gates are a *separate* axis from permissions, and that
hitting a ceiling is a sales prompt rather than a security error.
"""
from datetime import datetime, timedelta

import pytest

from auth.models import User
from billing.models import Plan, Subscription
from billing.plans import TRIAL_DAYS, features_for_tier
from extensions import db
from products.models import Product
from services import limits


@pytest.fixture
def business(register):
    _client, business_id = register()
    return business_id


def put_on(business_id, plan_code, **overrides):
    """Move a business onto a plan, with optional subscription overrides."""
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code=plan_code).one().id
    subscription.status = overrides.pop('status', 'active')
    for field, value in overrides.items():
        setattr(subscription, field, value)
    db.session.commit()
    return subscription


# ------------------------------------------------------------------ the plans

def test_all_six_plans_are_seeded():
    codes = {p.code for p in Plan.query.all()}
    assert codes == {'trial', 'free', 'basic', 'standard', 'advanced', 'custom'}


def test_tiers_inherit_everything_below_them():
    assert features_for_tier('free') == set()
    assert 'purchase_orders' in features_for_tier('basic')
    assert 'purchase_orders' in features_for_tier('standard')     # inherited
    assert 'credit_ledger' in features_for_tier('standard')
    assert 'credit_ledger' not in features_for_tier('basic')
    assert features_for_tier('basic') < features_for_tier('advanced')


def test_prices_match_the_agreed_band():
    prices = {p.code: p.price_monthly_ghs for p in Plan.query.all()}
    assert float(prices['basic']) == 99
    assert float(prices['standard']) == 199
    assert float(prices['advanced']) == 349
    assert prices['custom'] is None            # contact us


def test_annual_is_ten_months_for_twelve():
    """Priced generously on purpose: MoMo cannot auto-renew, so every annual sale
    removes eleven chances for a manual renewal to be forgotten."""
    for code in ('basic', 'standard', 'advanced'):
        plan = Plan.query.filter_by(code=code).one()
        assert float(plan.price_annual_ghs) == float(plan.price_monthly_ghs) * 10


# ------------------------------------------------------------------- the trial

def test_registration_starts_a_trial(business):
    subscription = Subscription.query.filter_by(business_id=business).one()
    assert subscription.status == 'trialing'
    assert subscription.plan.code == 'trial'
    assert subscription.days_left in (TRIAL_DAYS - 1, TRIAL_DAYS)


def test_trial_grants_advanced_features(business):
    assert limits.has_feature('purchase_orders', business)
    assert limits.has_feature('credit_ledger', business)
    assert limits.has_feature('audit_log', business)
    assert not limits.has_feature('multi_location', business)     # Custom only


def test_expired_trial_falls_back_to_free(business):
    put_on(business, 'trial', status='trialing',
           trial_ends_at=datetime.utcnow() - timedelta(days=1))

    assert limits.effective_plan(business).code == 'free'
    assert not limits.has_feature('purchase_orders', business)


def test_lapsed_payment_keeps_working_through_the_grace_period(business):
    put_on(business, 'standard', status='active',
           paid_through=datetime.utcnow() - timedelta(days=3))
    assert limits.effective_plan(business).code == 'standard'

    put_on(business, 'standard', status='active',
           paid_through=datetime.utcnow() - timedelta(days=30))
    assert limits.effective_plan(business).code == 'free'


# ------------------------------------------------------------------- the limits

def test_free_plan_caps_products(business, make_product):
    put_on(business, 'free')
    plan = Plan.query.filter_by(code='free').one()

    allowed, message = limits.can_add_product(business)
    assert allowed and message is None

    # Fill it to the cap
    for i in range(plan.max_products):
        make_product(business, sku=f'SKU-{i}', name=f'Product {i}')

    allowed, message = limits.can_add_product(business)
    assert not allowed
    assert '50 products' in message
    assert 'Upgrade' in message


def test_unlimited_plans_have_no_product_cap(business):
    put_on(business, 'advanced')
    assert Plan.query.filter_by(code='advanced').one().max_products is None
    assert limits.can_add_product(business) == (True, None)


def test_bulk_check_counts_the_whole_batch(business, make_product):
    put_on(business, 'basic')      # 200 products
    for i in range(198):
        make_product(business, sku=f'SKU-{i}', name=f'Product {i}')

    assert limits.can_add_product(business, adding=2)[0] is True
    assert limits.can_add_product(business, adding=3)[0] is False


def test_user_cap_is_enforced_at_the_route(business, app):
    """A ceiling is a warning and a redirect, never a 403."""
    put_on(business, 'free')       # 1 user, and the Owner is already that user

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    response = owner.post('/auth/users/add', data={
        'name': 'Efua', 'email': 'efua@x.example.com',
        'password': 'Str0ngPass!23', 'role_id': '4',
    }, follow_redirects=True)

    assert response.status_code == 200                       # not 403
    assert 'Upgrade' in response.get_data(as_text=True)
    assert User.query.filter_by(email='efua@x.example.com').first() is None


def test_product_cap_is_enforced_at_the_route(business, make_product, app):
    put_on(business, 'free')
    for i in range(50):
        make_product(business, sku=f'SKU-{i}', name=f'Product {i}')

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    from products.models import Brand, ItemGroup
    response = owner.post('/products/add', data={
        'name': 'One too many', 'cost_price': '1', 'unit_price': '2',
        'brand_id': str(Brand.query.filter_by(business_id=business).first().id),
        'item_group_id': str(ItemGroup.query.filter_by(business_id=business).first().id),
        'category_id': '0', 'sku': '', 'base_uom': '', 'purchase_uom': '',
        'units_per_purchase_uom': '', 'min_stock_alert': '0', 'quantity_in_stock': '0',
    }, follow_redirects=True)

    assert response.status_code == 200
    assert 'Upgrade' in response.get_data(as_text=True)
    assert Product.query.filter_by(name='One too many').first() is None


# ------------------------------------------------------------- feature gating

def test_feature_gate_blocks_a_route_the_plan_excludes(business, app):
    put_on(business, 'free')       # no purchase_orders

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    response = owner.get('/purchases/', follow_redirects=True)

    assert response.status_code == 200                       # redirected, not 403
    assert 'not included in your current plan' in response.get_data(as_text=True)


def test_feature_gate_allows_the_route_once_the_plan_includes_it(business, app):
    put_on(business, 'basic')      # purchase_orders included

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    assert owner.get('/purchases/').status_code == 200


def test_permission_and_feature_are_independent_gates(business, make_staff):
    """An Owner on Free cannot open purchasing (not paid for). Sales Staff on
    Advanced cannot either (no permission). Neither check implies the other."""
    put_on(business, 'advanced')
    staff = make_staff(business, 'Sales Staff', 'sales@x.example.com')
    assert staff.get('/purchases/').status_code == 403        # permission denied

    put_on(business, 'free')
    inventory = make_staff(business, 'Inventory Staff', 'inv@x.example.com')
    response = inventory.get('/purchases/', follow_redirects=True)
    assert 'not included in your current plan' in response.get_data(as_text=True)


def test_audit_log_is_an_advanced_feature(business, app):
    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    put_on(business, 'advanced')
    assert owner.get('/auth/audit').status_code == 200

    put_on(business, 'standard')
    response = owner.get('/auth/audit', follow_redirects=True)
    assert 'not included in your current plan' in response.get_data(as_text=True)


def test_a_business_without_a_subscription_falls_back_to_free(business):
    Subscription.query.filter_by(business_id=business).delete()
    db.session.commit()

    assert limits.effective_plan(business).code == 'free'
    assert not limits.has_feature('purchase_orders', business)
