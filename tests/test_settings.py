"""Business settings, walk-in debts, and the discount ceiling they unlock.

Every field on this page already existed on the Business row with no way to
change it. max_discount_percent is the one that mattered: it defaults to 0, so
the whole Stage 1.5 discount system - the sales.discount permission, the
ceiling, the never-below-cost floor, the deviation audit trail - was finished
code that no business could switch on.
"""
import datetime
import io
from decimal import Decimal

import pytest

from auth.models import Business
from extensions import db
from sales.models import Sale

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    product = make_product(business_id, unit_price='100.00', cost_price='60.00', stock=500)
    return client, business_id, product


def sell(client, product, quantity=2, price='100.00', customer_id='0',
         customer_name='', settlement='credit'):
    return client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(),
        'customer_id': customer_id,
        'customer_name': customer_name,
        'items-0-product_id': str(product.id),
        'items-0-quantity': str(quantity),
        'items-0-price_at_sale': price,
        'settlement': settlement,
        'payment_method': 'cash',
        'payment_reference': '',
        'amount_paid': '0',
    }, follow_redirects=True)


# --- walk-in customers -----------------------------------------------------

def test_a_walk_in_name_survives_the_sale(shop):
    """It used to be passed to the invoice as a URL parameter and never stored,
    so it was gone on reload and the debt was anonymous forever after."""
    client, _business_id, product = shop
    sell(client, product, customer_name='Kojo at Circle')

    sale = Sale.query.one()
    assert sale.customer_id is None
    assert sale.customer_name == 'Kojo at Circle'
    assert sale.buyer_name == 'Kojo at Circle'


def test_a_registered_customer_does_not_get_a_second_copy_of_their_name(shop, register):
    """Two names for one buyer can disagree; the customer record is the truth."""
    from sales.models import Customer
    client, business_id, product = shop
    customer = Customer(business_id=business_id, name='Madina Provisions')
    db.session.add(customer)
    db.session.commit()

    sell(client, product, customer_id=str(customer.id), customer_name='typed by mistake')

    sale = Sale.query.one()
    assert sale.customer_name is None
    assert sale.buyer_name == 'Madina Provisions'


def test_walk_in_debts_are_listed_one_by_one(shop):
    """The ageing table groups by customer, so every walk-in collapsed into a
    single row with nothing to click and no way to take their money."""
    client, _business_id, product = shop
    sell(client, product, quantity=2, customer_name='Kojo at Circle')     # 200
    sell(client, product, quantity=3, customer_name='Ama at Kaneshie')    # 300

    body = client.get('/credit/walk-ins').get_data(as_text=True)
    assert 'Kojo at Circle' in body
    assert 'Ama at Kaneshie' in body
    # Each has to be individually settleable, which is the whole point.
    for sale in Sale.query.all():
        assert f'/credit/sale/{sale.id}/pay' in body


def test_the_credit_dashboard_links_to_the_walk_in_page(shop):
    client, _business_id, product = shop
    sell(client, product, customer_name='Kojo at Circle')

    body = client.get('/credit/').get_data(as_text=True)
    assert '/credit/walk-ins' in body


def test_a_walk_in_debt_can_actually_be_paid_off(shop):
    client, _business_id, product = shop
    sell(client, product, quantity=2, customer_name='Kojo at Circle')      # 200
    sale = Sale.query.one()

    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '200.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    from services import credit
    assert credit.walk_in_sales(sale.business_id) == []


# --- settings --------------------------------------------------------------

def save_settings(client, **overrides):
    data = {
        'name': 'Accra Beverages', 'address': 'Accra', 'contact_number': '024',
        'expiry_alert_days': '30', 'max_discount_percent': '0',
    }
    data.update(overrides)
    return client.post('/auth/settings', data=data, follow_redirects=True)


def test_settings_save(shop):
    client, business_id, _product = shop
    save_settings(client, name='Accra Beverage Distributors',
                  contact_number='0302 555 000', expiry_alert_days='14')

    business = Business.query.get(business_id)
    assert business.name == 'Accra Beverage Distributors'
    assert business.contact_number == '0302 555 000'
    assert business.expiry_alert_days == 14


def test_a_zero_discount_ceiling_is_savable(shop):
    """InputRequired, not DataRequired: 0 is the default and a meaningful value -
    it switches discounting off - so it must not read as a missing field."""
    client, business_id, _product = shop
    save_settings(client, max_discount_percent='10')
    save_settings(client, max_discount_percent='0')

    assert Business.query.get(business_id).max_discount_percent == Decimal('0')


def test_a_ceiling_over_100_is_refused(shop):
    """Above 100 the discount floor goes negative, silently disabling the limit
    it exists to enforce. There is a CHECK constraint; the form must not reach it."""
    client, business_id, _product = shop
    save_settings(client, max_discount_percent='150')

    assert Business.query.get(business_id).max_discount_percent == Decimal('0')


def test_staff_without_the_permission_cannot_open_settings(shop, make_staff):
    _client, business_id, _product = shop
    manager = make_staff(business_id, 'Manager', 'ama@ab.example.com')

    assert manager.get('/auth/settings').status_code == 403


def test_the_settings_page_is_the_switch_for_discounting(shop):
    """The point of the whole page. With the ceiling at its default of 0 a
    discounted sale is refused; raising it here lets the same sale through."""
    client, business_id, product = shop

    sell(client, product, quantity=2, price='90.00')
    assert Sale.query.count() == 0, 'a discount was accepted with the ceiling at 0'

    save_settings(client, max_discount_percent='15')

    sell(client, product, quantity=2, price='90.00')          # 10% below list
    assert Sale.query.count() == 1
    assert Sale.query.one().items[0].price_at_sale == Decimal('90.00')


def test_a_discount_past_the_ceiling_is_still_refused(shop):
    client, _business_id, product = shop
    save_settings(client, max_discount_percent='5')

    sell(client, product, quantity=2, price='80.00')          # 20% below list
    assert Sale.query.count() == 0


def test_a_discount_change_is_audited(shop):
    """It is a money control - who widened it, and when, has to be answerable."""
    from auth.models import AuditLog
    client, _business_id, _product = shop
    save_settings(client, max_discount_percent='25')

    entry = AuditLog.query.filter_by(action='settings.update').one()
    assert '25' in entry.details_json


# --- logo ------------------------------------------------------------------

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
       b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
       b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


def upload_logo(client, blob=PNG, filename='logo.png'):
    return client.post('/auth/settings', data={
        'name': 'Accra Beverages', 'address': 'Accra', 'contact_number': '024',
        'expiry_alert_days': '30', 'max_discount_percent': '0',
        'logo': (io.BytesIO(blob), filename),
    }, content_type='multipart/form-data', follow_redirects=True)


def test_a_logo_is_stored_and_served(shop):
    """In the row, not on disk: the container is rebuilt on every deploy, so a
    logo written to the filesystem would vanish at the next release."""
    client, business_id, _product = shop
    upload_logo(client)

    assert Business.query.get(business_id).logo_data == PNG
    response = client.get('/auth/business/logo')
    assert response.status_code == 200
    assert response.data == PNG


def test_a_logo_is_not_visible_to_another_business(shop, register):
    """The route takes no id - it reads the caller's own business - so there is
    nothing to tamper with. This proves that, rather than assuming it."""
    client, _business_id, _product = shop
    upload_logo(client)

    other, _other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    assert other.get('/auth/business/logo').status_code == 404


def test_a_non_image_is_refused(shop):
    client, business_id, _product = shop
    upload_logo(client, blob=b'MZ\x90\x00 not an image', filename='payload.exe')

    assert Business.query.get(business_id).logo_data is None
