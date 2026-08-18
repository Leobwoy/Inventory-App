"""Stage W7 — the sale form opens on the unit the product is sold in.

The last of the stage, and the smallest. `sell_unit` defaulted to `'base'`, so
every line of every sale started on Single and a wholesaler had to press Carton
each time. `uom.default_sell_unit` already returned the pack first for a product
that has one; nothing called it.

The old code only re-selected when the checked unit was *not on offer*, so a
"both" product - the common case - kept the pre-checked Single forever. A
packs-only product happened to work, because Single was not on offer at all.
"""
import datetime
import re
from decimal import Decimal

import pytest

from extensions import db
from sales.models import Sale, SaleItem
from services import uom

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    both = make_product(business_id, sku='CLUB-330', name='Club Beer 330ml',
                        unit_price='43.75', cost_price='38.40', stock=480,
                        base_uom='bottle', purchase_uom='carton',
                        units_per_purchase_uom=24, pack_price='1050.00',
                        sell_unit='both')
    packs_only = make_product(business_id, sku='MALT-330', name='Malta Guinness',
                              unit_price='20.00', cost_price='16.00', stock=240,
                              base_uom='bottle', purchase_uom='carton',
                              units_per_purchase_uom=12, pack_price='230.00',
                              sell_unit='purchase')
    loose = make_product(business_id, sku='SWEETS-1', name='Loose Sweets',
                         unit_price='1.00', cost_price='0.60', stock=50)
    return client, business_id, both, packs_only, loose


def payload(page):
    import json
    blob = re.search(r'id="product-prices-data"[^>]*>(.*?)</script>', page, re.S)
    assert blob, 'the sale form lost its price data'
    return json.loads(blob.group(1))


# --- which unit the form starts on -------------------------------------------

def test_a_product_sold_both_ways_opens_on_the_carton(shop):
    """The case that was broken. Both units are on offer, so nothing forced a
    change and the pre-checked Single survived."""
    _client, _business_id, both, _packs, _loose = shop

    assert uom.sell_units(both) == [uom.PURCHASE, uom.BASE]
    assert uom.default_sell_unit(both) == uom.PURCHASE


def test_the_form_is_told_which_unit_to_open_each_product_on(shop):
    """The page cannot work it out - `sell_unit` is not in the payload - so the
    server sends the answer next to the units it already sends."""
    client, _business_id, both, packs, loose = shop

    data = payload(client.get('/sales/add').get_data(as_text=True))

    assert data[str(both.id)]['default'] == 'purchase'
    assert data[str(packs.id)]['default'] == 'purchase'
    assert data[str(loose.id)]['default'] == 'base'


def test_loose_goods_are_never_offered_a_carton(shop):
    client, _business_id, _both, _packs, loose = shop

    data = payload(client.get('/sales/add').get_data(as_text=True))

    assert data[str(loose.id)]['units'] == ['base']


# --- a refused sale must not lose the units that were chosen -----------------

def test_a_fresh_form_and_a_refused_one_are_told_apart(shop):
    """The page defaults each line on a fresh form and leaves the units alone on
    a re-render. `request.method` carries that, so it needs no variable from the
    route - this template is rendered from five places and one of them has
    already shipped a bug by forgetting one.
    """
    client, _business_id, both, _packs, _loose = shop

    fresh = client.get('/sales/add').get_data(as_text=True)
    assert 'data-repost="0"' in fresh

    # More than there is in stock, so the form comes back refused rather than
    # redirecting. Omitting sale_date does not work: it defaults to today, which
    # is a fix from earlier in this project, not an oversight.
    refused = client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0',
        'items-0-product_id': str(both.id),
        'items-0-quantity': '900', 'items-0-sell_unit': 'base',
        'settlement': 'paid',
    }).get_data(as_text=True)
    assert 'data-repost="1"' in refused

    checked = re.findall(r'<input[^>]*name="items-0-sell_unit"[^>]*>', refused)
    chosen = [tag for tag in checked if 'checked' in tag]
    assert chosen, 'no unit came back checked at all'
    assert 'value="base"' in chosen[0], 'the chosen unit was thrown away'


# --- the server does not depend on the page ----------------------------------

def test_a_packs_only_product_posted_without_a_unit_still_sells_a_carton(shop):
    """With no script running, or a trimmed form, the posted unit is `base` -
    which a packs-only product does not offer. That used to fall through to
    singles and sell twelve bottles at a bottle's price."""
    client, _business_id, _both, packs, _loose = shop

    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0',
        'items-0-product_id': str(packs.id), 'items-0-quantity': '2',
        'items-0-sell_unit': 'base', 'settlement': 'paid',
    }, follow_redirects=True)

    line = SaleItem.query.order_by(SaleItem.id.desc()).first()
    assert line.sell_unit == 'purchase'
    assert line.quantity == 24, 'two cartons of twelve did not move 24 bottles'
    # 230 over 12 is 19.1666... which six decimals cannot hold exactly, so the
    # stored product is 460.000008. Asserted at the boundary where a person
    # reads or pays it, which is where every other money check in this project
    # sits - the invoice formats to 2dp and credit quantises before comparing.
    assert line.price_per_sold_unit == Decimal('230.00')
    total = line.price_at_sale * line.quantity
    assert total.quantize(Decimal('0.01')) == Decimal('460.00')


def test_the_fallback_cannot_hand_out_a_unit_the_product_refuses(shop):
    """It resolves through `sell_units`, which is already filtered by the plan
    and by whether the product has a real pack - so widening the fallback cannot
    widen what may be sold."""
    client, _business_id, _both, _packs, loose = shop

    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': '0',
        'items-0-product_id': str(loose.id), 'items-0-quantity': '3',
        'items-0-sell_unit': 'purchase', 'settlement': 'paid',
    }, follow_redirects=True)

    line = SaleItem.query.order_by(SaleItem.id.desc()).first()
    assert line.sell_unit == 'base'
    assert line.quantity == 3, 'a product with no pack was multiplied'
