"""Onboarding — F-01.

A new business could not create a single product: brand and item group are
required, neither was seeded, and all four templates for creating them were
missing with no navigation to reach the routes.
"""
from auth.models import Business, User
from products.models import Brand, ItemGroup, Product


def test_registration_creates_business_and_owner(register):
    _c, business_id = register()

    business = Business.query.get(business_id)
    assert business is not None

    owner = User.query.filter_by(business_id=business_id).one()
    assert owner.role.name == 'Owner'
    assert owner.is_owner
    assert owner.last_login_at is None      # not set until an actual login


def test_registration_seeds_catalogue_fallbacks(register):
    """Without these the first product cannot be saved at all."""
    _c, business_id = register()

    assert [b.name for b in Brand.query.filter_by(business_id=business_id)] == ['Generic']
    assert [g.name for g in ItemGroup.query.filter_by(business_id=business_id)] == ['Uncategorized']


def test_catalogue_pages_render(register):
    """These four routes raised TemplateNotFound - the templates did not exist."""
    client, _ = register()
    for path in ['/products/brands', '/products/item_groups', '/products/categories']:
        assert client.get(path).status_code == 200, path


def test_product_saves_with_only_the_essential_fields(register):
    """Name, prices, brand and item group. Everything else must default (D7)."""
    client, business_id = register()
    brand = Brand.query.filter_by(business_id=business_id).first()
    group = ItemGroup.query.filter_by(business_id=business_id).first()

    client.post('/products/add', data={
        'name': 'BelAqua 750ml', 'cost_price': '2.50', 'unit_price': '3.50',
        'brand_id': str(brand.id), 'item_group_id': str(group.id), 'category_id': '0',
        'sku': '', 'base_uom': '', 'purchase_uom': '', 'units_per_purchase_uom': '',
        'min_stock_alert': '0', 'quantity_in_stock': '0',
    }, follow_redirects=True)

    product = Product.query.filter_by(name='BelAqua 750ml').one()
    assert product.sku                          # auto-generated
    assert product.base_uom == 'pcs'
    assert product.purchase_uom == 'pcs'        # falls back to base
    assert product.units_per_purchase_uom == 1
    assert product.min_stock_alert == 0         # zero must be storable
    assert product.quantity_in_stock == 0       # stock only enters via receipt


def test_generated_skus_are_unique(register):
    client, business_id = register()
    brand = Brand.query.filter_by(business_id=business_id).first()
    group = ItemGroup.query.filter_by(business_id=business_id).first()

    for name in ['Water A', 'Water B', 'Water C']:
        client.post('/products/add', data={
            'name': name, 'cost_price': '1', 'unit_price': '2',
            'brand_id': str(brand.id), 'item_group_id': str(group.id), 'category_id': '0',
            'sku': '', 'base_uom': '', 'purchase_uom': '', 'units_per_purchase_uom': '',
            'min_stock_alert': '0', 'quantity_in_stock': '0',
        }, follow_redirects=True)

    skus = [p.sku for p in Product.query.all()]
    assert len(skus) == 3
    assert len(set(skus)) == 3


def test_cannot_attach_another_businesses_brand(register, client, app):
    """A posted foreign key must never be trusted."""
    owner_a, business_a = register(name='Alpha', email='a@x.example.com')
    _owner_b, business_b = register(name='Beta', email='b@x.example.com', c=app.test_client())

    foreign_brand = Brand.query.filter_by(business_id=business_b).first()
    group_a = ItemGroup.query.filter_by(business_id=business_a).first()

    owner_a.post('/products/add', data={
        'name': 'Should Not Save', 'cost_price': '1', 'unit_price': '2',
        'brand_id': str(foreign_brand.id), 'item_group_id': str(group_a.id),
        'category_id': '0', 'sku': '', 'base_uom': '', 'purchase_uom': '',
        'units_per_purchase_uom': '', 'min_stock_alert': '0', 'quantity_in_stock': '0',
    }, follow_redirects=True)

    assert Product.query.filter_by(name='Should Not Save').first() is None


def test_login_records_last_login(register, client):
    register()
    client.get('/auth/logout')
    client.post('/auth/login', data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
                follow_redirects=True)
    assert User.query.filter_by(email='owner@ab.example.com').one().last_login_at is not None


def test_deactivated_account_cannot_log_in(register, app):
    from extensions import db
    register()
    user = User.query.filter_by(email='owner@ab.example.com').one()
    user.is_active = False
    db.session.commit()

    response = app.test_client().post(
        '/auth/login',
        data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'},
        follow_redirects=True,
    )
    assert 'deactivated' in response.get_data(as_text=True)


def test_login_ignores_absolute_next_target(register, client):
    """The next parameter was followed unvalidated - an open redirect (F-31)."""
    register()
    client.get('/auth/logout')
    response = client.post('/auth/login?next=https://evil.example/steal',
                           data={'email': 'owner@ab.example.com', 'password': 'Str0ngPass!23'})
    # Assert the redirect happened: a 200 (failed login) would leave Location
    # empty and pass the check below without ever exercising the redirect path.
    assert response.status_code == 302
    assert 'evil.example' not in response.headers.get('Location', '')
    assert response.headers['Location'] in ('/', 'http://localhost/')
