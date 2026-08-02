"""Shared fixtures.

Runs against real PostgreSQL rather than SQLite: the migrations use PostgreSQL
syntax (ON CONFLICT, = ANY(:codes)) and the FEFO ordering depends on NULLS LAST,
so SQLite would test something other than what ships.

The schema is built once per session by running the migration chain - the same
path a deploy takes, which means a broken chain fails the suite (F-02 shipped
precisely because nothing ever exercised it). Between tests the data tables are
truncated while the seeded role and permission rows are kept.
"""
import os
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import text

TEST_DB = os.environ.get('TEST_DB_NAME', 'tracktrack_test')
ADMIN_URL = os.environ.get(
    'TEST_ADMIN_URL', 'postgresql://postgres:postgres123@localhost:5432/postgres'
)
TEST_URL = ADMIN_URL.rsplit('/', 1)[0] + '/' + TEST_DB

PASSWORD = 'Str0ngPass!23'

# Truncated between tests. Order is irrelevant with CASCADE, but role, permission
# and role_permission are deliberately absent: they are seeded reference data.
DATA_TABLES = [
    'user_permission', 'audit_log', 'sale_item', 'sale', 'stock_batch',
    'purchase_order_item', 'purchase_order', 'purchase', 'product',
    'item_group', 'brand', 'category', 'supplier', 'customer', '"user"', 'business',
]


class IsolatedClient(FlaskClient):
    """A test client that gives every request its own application context.

    Tests hold an app context open so they can query models directly. Flask
    reuses the top app context for a request rather than pushing a new one, and
    Flask-Login caches the signed-in user on that context's `g`. Without this,
    the user from one request stays "logged in" for the next - so a second
    registration would see current_user.is_authenticated and redirect straight
    out, silently creating nothing.

    Pushing a fresh context per request also lets Flask-SQLAlchemy's teardown
    fire, so each request gets a clean session.
    """

    def open(self, *args, **kwargs):
        from extensions import db

        ctx = self.application.app_context()
        ctx.push()
        try:
            return super().open(*args, **kwargs)
        finally:
            ctx.pop()
            # The request committed on its own session. The test's session still
            # holds those rows in its identity map, and Query.get() would serve
            # the stale copy without touching the database - so a status or a
            # stock level would read as it was before the request.
            db.session.expire_all()


@pytest.fixture(scope='session')
def app():
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(ADMIN_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(TEST_DB)))
        cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(TEST_DB)))
    conn.close()

    os.environ['DATABASE_URL'] = TEST_URL
    from app import create_app
    from flask_migrate import upgrade

    application = create_app()
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    application.test_client_class = IsolatedClient

    with application.app_context():
        upgrade()          # the real chain, not create_all()

    yield application


@pytest.fixture(autouse=True)
def app_context(app):
    """Give every test a clean database and an application context.

    The context stays open for the whole test so fixtures and assertions can
    query models directly, the way the routes do.
    """
    from extensions import db

    with app.app_context():
        db.session.execute(text(f'TRUNCATE {", ".join(DATA_TABLES)} RESTART IDENTITY CASCADE'))
        db.session.commit()
        yield
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

@pytest.fixture
def register(client):
    """Register a business and return (client, business_id). Client is logged in as Owner."""
    def _register(name='Accra Beverages', email='owner@ab.example.com', c=None):
        # A client that has already registered carries a session cookie, and
        # /auth/register redirects an authenticated user straight out. Default to
        # the shared client for the first call and a fresh one after that, so a
        # second register() cannot silently create nothing.
        if c is None:
            c = client if not _register.used else app.test_client()
            _register.used = True
        c.post('/auth/register', data={
            'business_name': name, 'business_address': 'Accra', 'business_contact': '024',
            'user_name': 'Owner', 'email': email,
            'password': PASSWORD, 'confirm_password': PASSWORD,
        }, follow_redirects=True)
        from auth.models import Business
        business = Business.query.filter_by(name=name).first()
        # None when registration was meant to fail (e.g. a duplicate email), so
        # tests can assert on the rejection rather than blowing up in the fixture.
        return c, (business.id if business else None)

    _register.used = False
    return _register


@pytest.fixture
def make_staff(app):
    """Create a staff user on a role preset and return a logged-in client."""
    def _make(business_id, role_name, email, permissions=None):
        from werkzeug.security import generate_password_hash
        from auth.models import Role, User
        from extensions import db

        user = User(
            business_id=business_id, name=role_name, email=email,
            password_hash=generate_password_hash(PASSWORD),
            role_id=Role.query.filter_by(name=role_name).first().id,
            must_change_password=False,
        )
        db.session.add(user)
        db.session.flush()
        user.apply_role_preset(role_name)
        if permissions is not None:
            user.set_permissions(permissions)
        db.session.commit()

        c = app.test_client()
        c.post('/auth/login', data={'email': email, 'password': PASSWORD}, follow_redirects=True)
        return c
    return _make


@pytest.fixture
def make_product(app):
    """Create a product, optionally with opening stock as a batch."""
    def _make(business_id, sku='BA-750', name='BelAqua 750ml', unit_price='3.00',
              cost_price='2.00', stock=0, expiry=None):
        import datetime
        from extensions import db
        from products.models import Brand, ItemGroup, Product
        from purchases.models import StockBatch

        product = Product(
            business_id=business_id, name=name, sku=sku,
            unit_price=Decimal(unit_price), cost_price=Decimal(cost_price),
            quantity_in_stock=0, min_stock_alert=0,
            brand_id=Brand.query.filter_by(business_id=business_id).first().id,
            item_group_id=ItemGroup.query.filter_by(business_id=business_id).first().id,
            base_uom='pcs', purchase_uom='pcs', units_per_purchase_uom=1,
        )
        db.session.add(product)
        db.session.flush()
        if stock:
            db.session.add(StockBatch(
                business_id=business_id, product_id=product.id, batch_number=f'{sku}-SEED',
                quantity_received=stock, quantity_remaining=stock,
                received_date=datetime.date.today(), expiry_date=expiry,
            ))
            product.quantity_in_stock = stock
        db.session.commit()
        return product
    return _make


@pytest.fixture
def make_po(app):
    """Create an ordered purchase order with one line. Returns (po, item)."""
    def _make(business_id, product, quantity=100, unit_cost='2.00'):
        import datetime
        from extensions import db
        from products.models import Supplier
        from purchases.models import PurchaseOrder, PurchaseOrderItem

        supplier = Supplier.query.filter_by(business_id=business_id).first()
        if not supplier:
            supplier = Supplier(business_id=business_id, name='Voltic Ghana')
            db.session.add(supplier)
            db.session.flush()

        po = PurchaseOrder(business_id=business_id, supplier_id=supplier.id,
                           status='ordered', order_date=datetime.date.today())
        db.session.add(po)
        db.session.flush()
        item = PurchaseOrderItem(po_id=po.id, product_id=product.id,
                                 quantity_ordered=quantity, quantity_received=0,
                                 unit_cost=Decimal(unit_cost))
        db.session.add(item)
        db.session.commit()
        return po, item
    return _make
