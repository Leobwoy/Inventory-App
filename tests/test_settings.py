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


# --- discount is visible, not just enforced --------------------------------

def test_a_discounted_line_records_what_it_was_discounted_from(shop):
    """Product prices move, so a discount cannot be recovered later by comparing
    against today's list price - that would invent discounts that never happened
    and hide ones that did. The price on the day is kept with the line."""
    client, _business_id, product = shop
    save_settings(client, max_discount_percent='20')

    sell(client, product, quantity=2, price='85.00')

    item = Sale.query.one().items[0]
    assert item.price_at_sale == Decimal('85.00')
    assert item.list_price == Decimal('100.00')
    assert item.discount == Decimal('15.00')
    assert item.discount_percent == Decimal('15.00')
    assert item.was_discounted


def test_a_sale_at_list_price_is_not_marked_as_discounted(shop):
    client, _business_id, product = shop
    sell(client, product, quantity=2, price='100.00')

    sale = Sale.query.one()
    assert sale.items[0].list_price == Decimal('100.00')
    assert not sale.items[0].was_discounted
    assert sale.total_discount == Decimal('0')


def test_the_sale_totals_its_discount_across_lines(shop):
    client, _business_id, product = shop
    save_settings(client, max_discount_percent='20')
    sell(client, product, quantity=4, price='90.00')          # 10 off x 4

    assert Sale.query.one().total_discount == Decimal('40.00')


def test_the_invoice_shows_the_discount(shop):
    """It was enforced and audited but invisible - the customer holding the
    invoice could not see they had been given anything."""
    client, _business_id, product = shop
    save_settings(client, max_discount_percent='20')
    sell(client, product, quantity=2, price='85.00')
    sale = Sale.query.one()

    body = client.get(f'/sales/invoice/{sale.id}').get_data(as_text=True)
    assert 'Discount given' in body
    assert '30.00' in body            # 15 off x 2


def test_the_invoice_carries_the_business_identity(shop):
    """It said TrackTrack and showed our logo no matter whose business it was."""
    client, _business_id, product = shop
    save_settings(client, name='Accra Beverage Distributors',
                  address='Spintex Road', contact_number='0302 555 000')
    sell(client, product)
    sale = Sale.query.one()

    body = client.get(f'/sales/invoice/{sale.id}').get_data(as_text=True)
    # Assert on the invoice's own heading, not merely on the name appearing
    # somewhere in the page - it is also in the sidebar, so a looser check
    # passes even with the heading hardcoded back to ours.
    header = body.split('id="invoice-area"', 1)[1].split('</div>', 6)[0]
    assert 'Accra Beverage Distributors' in header
    assert 'TrackTrack' not in header
    assert 'Spintex Road' in body
    assert '0302 555 000' in body
    # Our credit stays regardless of how the business brands the rest.
    assert 'Made by TrackTrack' in body


def test_the_invoice_falls_back_to_our_logo(shop):
    client, _business_id, product = shop
    sell(client, product)
    sale = Sale.query.one()

    body = client.get(f'/sales/invoice/{sale.id}').get_data(as_text=True)
    assert 'static/logo.png' in body

    upload_logo(client)
    body = client.get(f'/sales/invoice/{sale.id}').get_data(as_text=True)
    assert '/auth/business/logo' in body


def test_a_walk_in_phone_is_kept_and_shown(shop):
    client, _business_id, product = shop
    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0',
        'customer_name': 'Kojo at Circle', 'customer_phone': '0244000111',
        'items-0-product_id': str(product.id), 'items-0-quantity': '2',
        'items-0-price_at_sale': '100.00', 'settlement': 'credit',
        'payment_method': 'cash', 'payment_reference': '', 'amount_paid': '0',
    }, follow_redirects=True)

    sale = Sale.query.one()
    assert sale.customer_phone == '0244000111'
    assert sale.buyer_phone == '0244000111'
    assert '0244000111' in client.get(f'/sales/invoice/{sale.id}').get_data(as_text=True)


def test_payment_notes_are_readable_afterwards(shop):
    """The payment form asks for notes; nothing ever showed them again, which
    makes the field worse than not having one."""
    from sales.models import Customer
    client, business_id, product = shop
    customer = Customer(business_id=business_id, name='Madina Provisions')
    db.session.add(customer)
    db.session.commit()

    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': str(customer.id),
        'customer_name': '', 'customer_phone': '',
        'items-0-product_id': str(product.id), 'items-0-quantity': '2',
        'items-0-price_at_sale': '100.00', 'settlement': 'credit',
        'payment_method': 'cash', 'payment_reference': '', 'amount_paid': '0',
    }, follow_redirects=True)
    sale = Sale.query.one()

    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '50.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': 'Paid at the depot, balance Friday',
    }, follow_redirects=True)

    body = client.get(f'/credit/customer/{customer.id}').get_data(as_text=True)
    assert 'Paid at the depot, balance Friday' in body


def test_the_sale_page_renders_the_cedi_sign(shop):
    """It was mangled to a,u by a file re-encoded through the wrong codepage."""
    client, _business_id, _product = shop
    body = client.get('/sales/add').get_data(as_text=True)

    assert '\u20b5' in body
    assert '\u00e2\u201a\u00b5' not in body
