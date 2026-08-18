"""The product form in the words a shopkeeper uses — Stage U4.

The old form asked for "Base UoM", "Purchase UoM" and "Units per Purchase UoM"
as three bare boxes, three rows above two price boxes that never said which unit
they meant. An owner typing a carton price into the single price produced a
product listing at twenty-four times its real price, and nothing caught it.

The field *names* are unchanged deliberately: tests/test_audit.py posts this
exact set, and renaming them would be a schema-shaped change dressed as wording.
"""
import re

import pytest

from extensions import db
from products.models import Product


@pytest.fixture
def shop(register):
    return register()


def form_page(client):
    response = client.get('/products/add')
    assert response.status_code == 200
    return response.get_data(as_text=True)


def product_payload(**overrides):
    data = {
        'name': 'Club Beer 330ml', 'sku': '', 'barcode': '', 'description': '',
        'unit_price': '48.00', 'cost_price': '38.40', 'quantity_in_stock': '0',
        'base_uom': 'bottle', 'purchase_uom': 'carton', 'units_per_purchase_uom': '24',
        # W2: the carton is what you type, so a packed product is refused
        # without both. The per-single figures above are still posted because
        # the same payload is reused for products with no pack at all.
        'pack_price': '1050.00', 'pack_cost': '921.60',
        'sell_unit': 'both', 'min_stock_alert': '1',
        'variant_label': '', 'size_value': '', 'size_unit': '',
    }
    data.update(overrides)
    return data


def add(client, app, **overrides):
    data = product_payload(**overrides)
    from products.models import Brand, ItemGroup
    from flask_login import current_user
    with client.session_transaction():
        pass
    brand = Brand.query.first()
    group = ItemGroup.query.first()
    data.setdefault('brand_id', str(brand.id))
    data.setdefault('item_group_id', str(group.id))
    data.setdefault('category_id', '0')
    return client.post('/products/add', data=data, follow_redirects=True)


# --- the words ---------------------------------------------------------------

def test_the_form_does_not_speak_in_database_terms(shop):
    """"Base UoM" means nothing to someone who sells drinks."""
    client, _business_id = shop
    page = form_page(client)

    for jargon in ('Base UoM', 'Purchase UoM', 'Units per Purchase UoM'):
        assert jargon not in page, f'the form still says "{jargon}"'


def test_the_form_asks_in_plain_words(shop):
    client, _business_id = shop
    page = form_page(client)

    assert 'What is one called?' in page
    assert 'How many in a pack?' in page
    assert 'What is a pack called?' in page


def test_the_prices_say_which_unit_they_are_in(shop):
    """The whole 24x mistake came from two price boxes that did not say."""
    client, _business_id = shop
    page = form_page(client)

    assert 'Price per single' in page
    assert 'Price per pack' in page
    assert 'Cost price, per single' in page


def test_the_form_reads_back_what_was_typed(shop):
    """The sentence is the guard. It puts "43.75 a bottle" on the screen
    before Save rather than after the first sale.

    W2 inverted the mistake it catches along with the boxes. A packed product
    has no singles box any more, so a carton price cannot be typed into one.
    What can still happen is the reverse - a bottle price typed into the
    carton box - and the signal for that is a carton selling below its cost.
    """
    client, _business_id = shop
    page = form_page(client)

    assert 'id="pack-summary"' in page
    assert 'that works out at ' in page, 'the per-single figure is not read back'
    assert 'is less than the ' in page, 'nothing warns about a single typed as a pack'


# --- errors, on every field ---------------------------------------------------

def test_every_field_can_show_why_it_was_refused(shop):
    """Exactly one of seventeen fields rendered an error before this. A refused
    product came back looking identical to the one that was sent."""
    client, _business_id = shop
    page = form_page(client)

    for field in ('name', 'unit_price', 'pack_price', 'min_stock_alert',
                  'base_uom', 'purchase_uom', 'units_per_purchase_uom',
                  'sell_unit', 'quantity_in_stock'):
        assert f"form.{field}.errors" not in page, 'template source leaked'
    # A real refusal must mark the field and say why.
    from products.models import Brand, ItemGroup
    body = client.post('/products/add', data=product_payload(
        name='', brand_id=str(Brand.query.first().id),
        item_group_id=str(ItemGroup.query.first().id), category_id='0',
    )).get_data(as_text=True)

    name_input = re.search(r'<input[^>]*name="name"[^>]*>', body)
    assert name_input, 'the name field is not on the page'
    assert 'is-invalid' in name_input.group(0), 'the refused name is unmarked'
    assert 'This field is required.' in body, 'nothing says why'


# --- a pack that is not a pack ------------------------------------------------

def test_a_pack_of_one_is_not_a_pack(shop, app):
    """"Both" on a product with no real pack would have the sale form offering a
    carton the server then refuses, which reads as the app being broken rather
    than the product being set up wrong."""
    client, _business_id = shop
    add(client, app, name='Loose Sweets', purchase_uom='', units_per_purchase_uom='1',
        pack_price='', sell_unit='both')

    product = Product.query.filter_by(name='Loose Sweets').one()
    assert product.sell_unit == 'base'


def test_a_pack_named_the_same_as_the_item_is_not_a_pack(shop, app):
    client, _business_id = shop
    add(client, app, name='Odd Setup', base_uom='pcs', purchase_uom='pcs',
        units_per_purchase_uom='12', sell_unit='both')

    assert Product.query.filter_by(name='Odd Setup').one().sell_unit == 'base'


def test_a_real_pack_is_kept(shop, app):
    from decimal import Decimal

    client, _business_id = shop
    add(client, app, name='Club Beer 330ml')

    product = Product.query.filter_by(name='Club Beer 330ml').one()
    assert product.sell_unit == 'both'
    assert product.pack_price == Decimal('1050.00')
    assert product.units_per_purchase_uom == 24


def test_a_packed_product_is_refused_without_a_carton_price(shop, app):
    """This asserted the opposite until W2, and the reversal is the stage.

    A blank pack price used to mean "a pack is count x the single price",
    which was reasonable while the single was the price somebody typed. It is
    not any more: the carton is the unit, so leaving its price blank is
    leaving the price blank. `uom.price_for` still reads a null that way for
    rows that predate this - see test_pack_pricing.py - the form just will not
    make a new one.
    """
    client, _business_id = shop
    add(client, app, name='No Pack Price', pack_price='')

    assert Product.query.filter_by(name='No Pack Price').count() == 0
