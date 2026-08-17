"""Choosing a product in a dialog — the fix for a table that could not hold one.

The measurement that started this: on a 1440px laptop the sale form's product
cell was 130px and the search box inside it 98px, while the longest product name
needed 169. Five columns wanted about a 1500px window, so every ordinary laptop
showed "BelA". Width tuning cannot fix five columns in 583px, so the product
picker left the row.

What is asserted here is deliberately not the layout - a test cannot see cramped.
It is the things that would break silently: that the plain <select> is still
there for a browser that runs no script, that a line's fields keep the names the
server reads, and that a purchase order can now carry more than one line at all.
"""
import datetime
import inspect
import re

import pytest
from werkzeug.datastructures import MultiDict

from extensions import db
from purchases.models import PurchaseOrder, PurchaseOrderItem

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    products = [make_product(business_id, sku=f'P{i}', name=name,
                             unit_price='3.00', cost_price='2.00', stock=100)
                for i, name in enumerate(['Club Beer 330ml', 'Voltic Water 500ml',
                                          'Malta Guinness 330ml'])]
    return client, business_id, products


def body(client, path):
    response = client.get(path)
    assert response.status_code == 200, f'{path} returned {response.status_code}'
    return response.get_data(as_text=True)


# --- the dialog is there, on both pages that choose a product ----------------

@pytest.mark.parametrize('path', ['/sales/add', '/purchases/add'])
def test_the_picker_is_on_the_page(shop, path):
    client, _business_id, _products = shop
    page = body(client, path)

    assert 'id="product-picker"' in page, 'the dialog itself is missing'
    assert 'js/picker.js' in page, 'nothing would open it'
    assert 'data-picker-for=".product-select"' in page, 'no button opens it'


@pytest.mark.parametrize('path', ['/sales/add', '/purchases/add'])
def test_the_plain_select_survives_for_a_browser_with_no_script(shop, path):
    """The button is shown and the select hidden by picker.js, never by the
    server. Rendering only the button would leave a phone whose script failed to
    download with no way to choose a product at all - and this is the page the
    business runs on."""
    client, _business_id, _products = shop
    page = body(client, path)

    select = re.search(r'<select[^>]*data-picker-select[^>]*>', page)
    assert select, 'the product select is not in the HTML at all'
    assert 'hidden' not in select.group(0), 'the server hid it; no script means no product'
    assert 'display:none' not in select.group(0).replace(' ', '')
    assert 'name="items-0-product_id"' in page


# --- a purchase order with more than one line -------------------------------

def test_the_purchase_order_page_can_add_a_line(shop):
    """It could not. There was no add-row control and no cloning script on that
    page, so every purchase order this app has ever created has had exactly one
    product on it."""
    client, _business_id, _products = shop
    page = body(client, '/purchases/add')

    assert 'id="add-line"' in page
    assert 'class="btn btn-outline-danger remove-line"' in page


def test_a_multi_line_order_is_recorded_in_full(shop):
    """Three lines, three products, three quantities - each bound to its own."""
    client, business_id, products = shop

    response = client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(),
        'items-0-product_id': str(products[0].id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'base', 'items-0-unit_cost': '2.00',
        'items-1-product_id': str(products[1].id), 'items-1-quantity_ordered': '20',
        'items-1-order_unit': 'base', 'items-1-unit_cost': '3.00',
        'items-2-product_id': str(products[2].id), 'items-2-quantity_ordered': '30',
        'items-2-order_unit': 'base', 'items-2-unit_cost': '4.00',
    }, follow_redirects=True)

    assert response.status_code == 200
    po = PurchaseOrder.query.filter_by(business_id=business_id).order_by(
        PurchaseOrder.id.desc()).first()
    assert po is not None
    lines = PurchaseOrderItem.query.filter_by(po_id=po.id).all()
    assert len(lines) == 3, f'{len(lines)} lines recorded, not 3'

    got = {line.product_id: line.quantity_ordered for line in lines}
    assert got == {products[0].id: 10, products[1].id: 20, products[2].id: 30}


def test_a_middle_line_removed_leaves_the_rest_bound_correctly(shop):
    """What the browser posts after removing the second of three lines: the
    survivors renumbered 0 and 1. Without the renumbering the POST carries a hole
    - items-0 and items-2 - and WTForms stops at the gap, so the last line is
    dropped without a word."""
    client, business_id, products = shop

    response = client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(),
        'items-0-product_id': str(products[0].id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'base', 'items-0-unit_cost': '2.00',
        'items-1-product_id': str(products[2].id), 'items-1-quantity_ordered': '30',
        'items-1-order_unit': 'base', 'items-1-unit_cost': '4.00',
    }, follow_redirects=True)

    assert response.status_code == 200
    po = PurchaseOrder.query.filter_by(business_id=business_id).order_by(
        PurchaseOrder.id.desc()).first()
    lines = PurchaseOrderItem.query.filter_by(po_id=po.id).all()
    assert {line.product_id for line in lines} == {products[0].id, products[2].id}
    assert products[1].id not in {line.product_id for line in lines}


def test_two_lines_sharing_an_index_lose_one_of_themselves(shop):
    """The failure renumbering exists to prevent, stated as a measured fact.

    A gap is *not* the problem - WTForms compacts items-0 + items-2 into two
    lines quite happily, which this test established by trying it. The problem is
    a collision: remove the middle of three rows and the survivors are 0 and 2,
    so a new row named from `length` becomes items-2 as well. Two lines then post
    under one set of names and the browser sends both values for each field.
    WTForms reads the first and the second line is gone, with nothing to see.
    """
    client, business_id, products = shop

    # A repeated name is what a real form sends when two rows share an index.
    # MultiDict, because a plain dict cannot hold the same key twice - which is
    # the entire situation being reproduced.
    client.post('/purchases/add', data=MultiDict([
        ('supplier_id', '0'), ('order_date', TODAY.isoformat()),
        ('items-0-product_id', str(products[0].id)),
        ('items-0-quantity_ordered', '10'),
        ('items-0-order_unit', 'base'), ('items-0-unit_cost', '2.00'),
        ('items-0-product_id', str(products[2].id)),
        ('items-0-quantity_ordered', '30'),
        ('items-0-order_unit', 'base'), ('items-0-unit_cost', '4.00'),
    ]), follow_redirects=True)

    po = PurchaseOrder.query.filter_by(business_id=business_id).order_by(
        PurchaseOrder.id.desc()).first()
    assert po is not None, 'the order was refused outright, which is not the point'
    lines = PurchaseOrderItem.query.filter_by(po_id=po.id).all()
    assert len(lines) == 1, (
        'a collision no longer loses a line; renumbering may have stopped being '
        'load-bearing, so check before trusting it')


def test_a_gap_in_the_indexes_is_harmless(shop):
    """Recorded because the obvious guess is wrong and cost a test. items-0 plus
    items-2, with no items-1, records both lines - WTForms closes the gap."""
    client, business_id, products = shop

    client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(),
        'items-0-product_id': str(products[0].id), 'items-0-quantity_ordered': '10',
        'items-0-order_unit': 'base', 'items-0-unit_cost': '2.00',
        'items-2-product_id': str(products[2].id), 'items-2-quantity_ordered': '30',
        'items-2-order_unit': 'base', 'items-2-unit_cost': '4.00',
    }, follow_redirects=True)

    po = PurchaseOrder.query.filter_by(business_id=business_id).order_by(
        PurchaseOrder.id.desc()).first()
    assert len(PurchaseOrderItem.query.filter_by(po_id=po.id).all()) == 2


# --- errors that were invisible ---------------------------------------------

def test_a_rejected_order_line_says_so(shop):
    """This page rendered no is-invalid and no invalid-feedback anywhere. A
    refused order came back looking exactly like the one that was sent."""
    client, _business_id, products = shop

    page = client.post('/purchases/add', data={
        'supplier_id': '0', 'order_date': TODAY.isoformat(),
        'items-0-product_id': str(products[0].id), 'items-0-quantity_ordered': '',
        'items-0-order_unit': 'base', 'items-0-unit_cost': '2.00',
    }).get_data(as_text=True)

    # Asserted on the field that actually failed, not on the page. Five other
    # fields on this form can carry is-invalid, so a bare `'is-invalid' in page`
    # passes with the quantity left unmarked - which is exactly what it stayed
    # green through when that mutation was tried.
    quantity = re.search(r'<input[^>]*name="items-0-quantity_ordered"[^>]*>', page)
    assert quantity, 'the quantity field is not on the page at all'
    assert 'is-invalid' in quantity.group(0), (
        'the refused quantity carries no mark: ' + quantity.group(0))
    # The words, not the class name. `'invalid-feedback' in page` is satisfied
    # by any of the other five fields' error slots, empty or not.
    assert 'This field is required.' in page, (
        'the field is marked but nothing says why')


def test_the_order_date_is_already_today(shop):
    """DataRequired renders `required`, so an empty date meant the browser
    refused to submit and said nothing. Same trap as the sale form."""
    client, _business_id, _products = shop

    assert f'value="{TODAY.isoformat()}"' in body(client, '/purchases/add')


# --- the crash that ate its own error message -------------------------------

def test_the_add_page_genuinely_needs_product_uom():
    """Establishes the dependency the next test guards. If the template stopped
    using product_uom this would fail and that test would be guarding nothing."""
    import pathlib

    template = pathlib.Path('templates/purchases/add.html').read_text(encoding='utf-8')
    assert 'product_uom|tojson' in template, (
        'the template no longer feeds product_uom to |tojson; the guarantee '
        'below is now about nothing')


def test_every_render_of_the_add_page_passes_product_uom():
    """One of the two render paths did not. `|tojson` on an Undefined raises,
    and that return sits inside the route's try, so `except Exception` swallowed
    it and replaced 'One of the selected products is no longer available' with
    the generic 'Something went wrong'. The specific message never once reached
    a user."""
    from purchases import routes

    source = inspect.getsource(routes.add_purchase)
    renders = re.findall(r"render_template\(\s*'purchases/add\.html'(.*?)\)",
                         source, re.S)
    assert renders, 'the route no longer renders this template by that name'
    for call in renders:
        assert 'product_uom' in call, (
            'a render of purchases/add.html omits product_uom, which the '
            'template requires: ' + call.strip()[:120])


# --- goods receipt reads request.form directly, so the names are the contract -

def test_the_receipt_keeps_the_field_names_the_route_reads(shop, make_po):
    """This page is not a WTForms form. The route reads request.form for
    qty_<id>, unit_<id>, batch_<id> and expiry_<id>, so a renamed input is not a
    validation error - it is a silently ignored delivery."""
    client, business_id, products = shop
    po, line = make_po(business_id, products[0], quantity=10)

    page = body(client, f'/purchases/receive/{po.id}')

    assert f'name="qty_{line.id}"' in page
    assert f'name="batch_{line.id}"' in page
    assert f'name="expiry_{line.id}"' in page
    # The button that fills every line, and the data the script reads off them.
    assert 'id="receive-all"' in page
    assert 'data-outstanding=' in page and 'data-per=' in page


@pytest.mark.parametrize('path', ['/sales/add', '/purchases/add'])
def test_the_button_says_it_opens_something(shop, path):
    """Reported from the running app: nothing indicated the product box could be
    tapped. It was true - the border computed to two thirds of a pixel at 10%
    white, invisible on a dark card, and the search icon was hidden the moment a
    product was chosen. An affordance that disappears once used is not one."""
    client, _business_id, _products = shop
    page = body(client, path)

    assert 'picker-caret' in page, 'nothing marks the button as a control'
    # Written as markup, not a CSS content escape: a unicode escape written
    # through tooling has arrived here as a control character three times.
    assert 'bi-chevron-down picker-caret' in page


def test_the_caret_stays_after_a_product_is_chosen(shop):
    """Only the leading magnifier goes; the caret is what keeps saying the row
    can be changed."""
    client, _business_id, _products = shop
    css = client.get('/static/css/style.css').get_data(as_text=True)

    hidden = css[css.index('.picker-button.is-chosen .picker-button-hint,'):]
    hidden = hidden[:hidden.index('}')]

    assert '.bi-search' in hidden, 'the magnifier is no longer the thing hidden'
    assert 'picker-caret' not in hidden, 'the caret is hidden once a product is chosen'


def test_the_picker_button_has_a_border_that_can_be_seen(shop):
    client, _business_id, _products = shop
    css = client.get('/static/css/style.css').get_data(as_text=True)

    # Anchored to the start of a line: `.picker-button {` also appears inside
    # `[data-line].line-enhanced .picker-button {`, which only sets display, and
    # this assertion happily read that instead.
    m = re.search(r'^\.picker-button\s*\{', css, re.M)
    assert m, 'no .picker-button rule'
    # Comments stripped: the rule explains that it used to be `dashed`, and the
    # assertion below read that explanation as the declaration.
    rule = re.sub(r'/\*.*?\*/', '', css[m.end():css.index('}', m.end())], flags=re.S)

    assert 'var(--input-border-strong)' in rule,         'back to a border nobody can see against the card'
    assert 'dashed' not in rule
