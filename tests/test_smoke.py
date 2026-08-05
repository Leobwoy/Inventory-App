"""Render every registered route.

This is the guard that would have caught most of the original audit findings in
CI: four routes rendered templates that did not exist, one report queried a
table nothing writes to, and a whole page rendered blank. All of it shipped
because nothing ever asked the app to render itself.
"""
import datetime

import pytest

TODAY = datetime.date.today()

# Endpoints excluded, with the reason each is not a gap in coverage.
SKIP = {
    'static',            # served by Flask
    'auth.logout',       # ends the session the other tests need
}


@pytest.fixture
def populated(register, make_product, make_po):
    """One business with a full chain: product, PO, receipt, sale, customer."""
    client, business_id = register()
    product = make_product(business_id, stock=0)
    po, item = make_po(business_id, product, quantity=100)

    client.post(f'/purchases/receive/{po.id}', data={
        'received_date': TODAY.isoformat(), f'qty_{item.id}': '100',
        f'batch_{item.id}': '', f'expiry_{item.id}': '',
    }, follow_redirects=True)

    client.post('/sales/customers/add', data={
        'name': 'Madina Retail', 'phone': '024', 'email': 'm@x.example.com', 'address': 'Madina',
    }, follow_redirects=True)

    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0', 'customer_name': 'Walk-in',
        'items-0-product_id': str(product.id), 'items-0-quantity': '10',
        'items-0-price_at_sale': '3.00',
    }, follow_redirects=True)

    return client, business_id, product, po


def _routes(app):
    for rule in sorted(app.url_map.iter_rules(), key=str):
        if rule.endpoint in SKIP or 'GET' not in rule.methods:
            continue
        yield rule


def test_every_get_route_renders(app, populated):
    client, business_id, product, po = populated

    from auth.models import User
    from products.models import Brand, Category, ItemGroup, Supplier
    from sales.models import Customer, Sale

    params = {
        'product_id': product.id,
        'po_id': po.id,
        'sale_id': Sale.query.first().id,
        'customer_id': Customer.query.first().id,
        'supplier_id': Supplier.query.first().id,
        'brand_id': Brand.query.filter_by(business_id=business_id).first().id,
        'item_group_id': ItemGroup.query.filter_by(business_id=business_id).first().id,
        'user_id': User.query.filter_by(business_id=business_id).first().id,
        'category_id': None,
    }
    if Category.query.first():
        params['category_id'] = Category.query.first().id

    failures = []
    checked = 0
    for rule in _routes(app):
        try:
            url = rule.build({k: v for k, v in params.items() if v is not None},
                             append_unknown=False)[1] if rule.arguments else str(rule)
        except Exception:
            continue        # cannot build a URL for it with the fixtures at hand
        response = client.get(url)
        checked += 1
        if response.status_code >= 500:
            failures.append(f'{url} -> {response.status_code}')

    assert failures == [], f'{len(failures)} route(s) failed: {failures}'
    assert checked >= 20, f'only exercised {checked} routes - the fixture is too thin'


def test_reports_carry_real_figures(populated):
    """The purchases report was permanently empty; sales row totals printed 0.00."""
    client, _business_id, _product, po = populated

    purchases = client.get('/reports/purchases').get_data(as_text=True)
    assert f'PO-{po.id}' in purchases

    sales = client.get('/reports/sales').get_data(as_text=True)
    assert '30.00' in sales      # 10 units at 3.00, and the footer must agree


def test_dashboard_product_count_is_not_capped(register, make_product):
    """The card rendered len(top_products), a list limited to 5."""
    client, business_id = register()
    for i in range(7):
        make_product(business_id, sku=f'SKU-{i}', name=f'Product {i}')

    body = client.get('/').get_data(as_text=True)
    assert '>7 <' in body.replace('\n', ' ') or '>7<' in body


def test_permission_grid_renders_for_a_staff_member(register, make_staff):
    """The route smoke test only ever reaches this page for the Owner, who is
    redirected away before it renders - so a template error here went unseen
    (loop.parent does not exist in Jinja, and the page raised UndefinedError)."""
    client, business_id = register()
    make_staff(business_id, 'Sales Staff', 'sales@x.example.com')

    from auth.models import User
    staff_id = User.query.filter_by(email='sales@x.example.com').one().id

    response = client.get(f'/auth/users/{staff_id}/permissions')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'sales.create' in body          # the grid actually rendered
    assert 'Toggle all' in body


def test_every_post_form_carries_a_csrf_token():
    """Six templates posted without one, so every bulk action 400'd (F-28)."""
    import pathlib
    import re

    # Matches method="post", method='post' and bare method=post. Checking only
    # for the double-quoted spelling would let an unprotected form slip past.
    post_form = re.compile(r'method\s*=\s*["\']?post["\']?', re.IGNORECASE)

    templates = pathlib.Path(__file__).resolve().parent.parent / 'templates'
    offenders = []
    for path in templates.rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        if post_form.search(text) and 'csrf_token' not in text and 'hidden_tag' not in text:
            offenders.append(path.name)
    assert offenders == [], f'templates posting without CSRF: {offenders}'
