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
    """Move a business onto a plan, with optional subscription overrides.

    An 'active' subscription gets a real future paid_through unless the caller
    supplies one. Leaving it null used to land every test on the branch where a
    missing date was read as "no expiry" - so the helper quietly modelled a
    subscription nobody had paid for, and hid the fail-open it created.
    """
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code=plan_code).one().id
    subscription.status = overrides.pop('status', 'active')
    if subscription.status == 'active' and 'paid_through' not in overrides:
        subscription.paid_through = datetime.utcnow() + timedelta(days=30)
    if subscription.status == 'trialing' and 'trial_ends_at' not in overrides:
        subscription.trial_ends_at = datetime.utcnow() + timedelta(days=14)
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
    # Exactly, not "give or take one". The tolerance here was accommodating the
    # truncation bug that made a fourteen-day trial read as thirteen.
    assert subscription.days_left == TRIAL_DAYS


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
    assert '20 active products' in message
    assert 'Upgrade' in message


# ------------------------------------------- the downgrade exploit, and its fix

def test_only_active_products_count_towards_the_limit(business, make_product):
    """Pay for one month of a big plan, bulk-load a catalogue, drop to free and
    keep trading on all of it - that is the obvious play, and counting every row
    rather than the active ones would allow it."""
    put_on(business, 'free')                    # 20 active products
    for i in range(30):
        make_product(business, sku=f'SKU-{i}', name=f'Product {i}')

    assert limits.active_product_count(business) == 30
    assert limits.can_add_product(business)[0] is False

    # Retiring eleven brings them back under the cap without deleting anything.
    for product in Product.query.filter_by(business_id=business).limit(11):
        product.is_active = False
    db.session.commit()

    assert Product.query.filter_by(business_id=business).count() == 30   # nothing lost
    assert limits.active_product_count(business) == 19
    assert limits.can_add_product(business)[0] is True


def test_reactivating_above_the_cap_is_blocked(business, make_product, app):
    """Otherwise a business over its cap could rotate an unlimited catalogue
    fifty products at a time."""
    put_on(business, 'free')
    products = [make_product(business, sku=f'SKU-{i}', name=f'Product {i}') for i in range(21)]
    products[0].is_active = False               # 20 active, exactly at the cap
    db.session.commit()
    retired_id = products[0].id

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    response = owner.post(f'/products/deactivate/{retired_id}', follow_redirects=True)

    assert 'Upgrade to add more' in response.get_data(as_text=True)
    assert Product.query.get(retired_id).is_active is False       # still off


def test_reactivating_within_the_cap_is_allowed(business, make_product, app):
    put_on(business, 'free')
    product = make_product(business, sku='ONLY-1')
    product.is_active = False
    db.session.commit()

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    owner.post(f'/products/deactivate/{product.id}', follow_redirects=True)

    assert Product.query.get(product.id).is_active is True


def test_bulk_upload_obeys_the_product_cap(business, app):
    """The spreadsheet import is the obvious way round a per-product limit."""
    import io
    import openpyxl

    put_on(business, 'free')                    # 20
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(['Name', 'SKU', 'Description', 'Unit Price', 'Qty'])
    for i in range(120):
        sheet.append([f'Bulk {i}', f'BULK-{i}', '', 2.0, 0])
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
               follow_redirects=True)
    response = owner.post('/products/upload', data={'file': (buffer, 'products.xlsx')},
                          content_type='multipart/form-data', follow_redirects=True)

    assert limits.active_product_count(business) == 20
    body = response.get_data(as_text=True)
    assert 'were not added because the Kiosk plan covers' in body


def test_suspended_staff_do_not_consume_a_seat(business, make_staff):
    put_on(business, 'basic')                   # 2 people
    make_staff(business, 'Manager', 'mgr@x.example.com')
    assert limits.can_add_user(business)[0] is False      # Owner + Manager = 2

    User.query.filter_by(email='mgr@x.example.com').one().is_active = False
    db.session.commit()

    assert limits.active_user_count(business) == 1
    assert limits.can_add_user(business)[0] is True


def test_unlimited_plans_have_no_product_cap(business):
    """Enterprise, not Distributor. Distributor had no ceiling until the caps
    were set deliberately (Kiosk 20, Shop 70, Depot 200, Distributor 500); the
    only plan that is still uncapped is the one sold by conversation."""
    put_on(business, 'custom')
    assert Plan.query.filter_by(code='custom').one().max_products is None
    assert limits.can_add_product(business) == (True, None)


def test_bulk_check_counts_the_whole_batch(business, make_product):
    put_on(business, 'basic')      # 70 products
    for i in range(68):
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


def test_permission_and_feature_are_independent_gates(business, make_staff, app):
    """An Owner on Free cannot open purchasing (not paid for). Sales Staff on
    Advanced cannot either (no permission). Neither check implies the other.

    The second half uses the Owner, which is what the sentence above always
    claimed. It used to create an Inventory Staff account on Free and check the
    message with that - and Kiosk has one seat, so once a downgrade started
    suspending people over the cap, the account was suspended by the time the
    page rendered. The setup was one the app itself would never allow; only a
    fixture writing straight to the table could build it.
    """
    put_on(business, 'advanced')
    staff = make_staff(business, 'Sales Staff', 'sales@x.example.com')
    assert staff.get('/purchases/').status_code == 403        # permission denied

    put_on(business, 'free')
    owner = app.test_client()
    owner.post('/auth/login', data={'email': 'owner@ab.example.com',
                                    'password': 'Str0ngPass!23'}, follow_redirects=True)
    response = owner.get('/purchases/', follow_redirects=True)
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


def test_a_subscription_with_no_paid_through_does_not_keep_a_paid_plan(business):
    """A null end date used to read as "no expiry", so one row written without
    one entitled a business to a paid plan permanently and silently. The only
    signal would have been the money never arriving."""
    subscription = Subscription.query.filter_by(business_id=business).one()
    subscription.plan_id = Plan.query.filter_by(code='advanced').one().id
    subscription.status = 'active'
    subscription.paid_through = None
    db.session.commit()

    assert limits.effective_plan(business).code == 'free'


def test_a_trial_with_no_end_date_does_not_run_forever(business):
    subscription = Subscription.query.filter_by(business_id=business).one()
    subscription.plan_id = Plan.query.filter_by(code='advanced').one().id
    subscription.status = 'trialing'
    subscription.trial_ends_at = None
    db.session.commit()

    assert limits.effective_plan(business).code == 'free'


def test_a_fourteen_day_trial_does_not_start_at_thirteen(business):
    """timedelta.days truncates, so the microseconds between writing the
    deadline and reading it were enough to lose a day. A customer who counts is
    right to feel short-changed by that."""
    subscription = Subscription.query.filter_by(business_id=business).one()
    subscription.status = 'trialing'
    subscription.trial_ends_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
    db.session.commit()

    assert subscription.days_left == TRIAL_DAYS


def test_part_of_a_day_still_counts_as_a_day(business):
    from billing.models import days_until

    now = datetime.utcnow()
    assert days_until(now + timedelta(hours=1), now) == 1
    assert days_until(now + timedelta(hours=25), now) == 2
    assert days_until(now - timedelta(hours=1), now) == 0
