"""The record-a-sale page — Phase C3 of the redesign.

The page splits into two panes: what is being bought, then who bought it and how
they paid. The split is presentation only. There is still one form, one POST and
one route; nothing is held in the session between the steps, so there is no
half-finished sale living anywhere and no second endpoint to secure.

Everything here is asserted against the server's own HTML rather than against
the browser, because the decisions that can silently ruin this page are all made
before it is sent: which pane opens, whether a failed field is behind a hidden
one, and whether the form still works when the script never runs.
"""
from datetime import date

import pytest

from extensions import db
from sales.models import Sale, SaleItem


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    product = make_product(business_id, unit_price='3.00', cost_price='2.00', stock=500)
    return client, business_id, product


def form_html(client):
    body = client.get('/sales/add').get_data(as_text=True)
    return body[body.index('<form method="post" id="sale-form"'):body.index('</form>')]


def attr(body, name):
    """The value of one attribute on the sale form's opening tag."""
    tag = body[body.index('<form method="post" id="sale-form"'):]
    tag = tag[:tag.index('>')]
    marker = name + '="'
    return tag[tag.index(marker) + len(marker):].split('"')[0]


# --- one form, not a wizard --------------------------------------------------

def test_both_panes_live_inside_the_one_form(shop):
    """The step 2 fields have to post with the step 1 fields. Outside the form
    they would simply not be sent, and every sale would record as a walk-in
    paid in cash, silently, with nothing to see on the page."""
    client, _business_id, _product = shop
    inside = form_html(client)

    for field in ('items-0-product_id', 'items-0-quantity', 'customer_id',
                  'sale_date', 'customer_name', 'customer_phone',
                  'settlement', 'payment_method', 'payment_reference'):
        assert 'name="' + field + '"' in inside, f'{field} is outside the form'


def test_stepping_is_the_browser_s_idea_only(shop):
    """Rendered with data-steps="off": both panes on the page, no step
    indicator, and the plain long form that worked before any of this. A
    browser whose script did not run still records a sale."""
    client, _business_id, _product = shop
    body = client.get('/sales/add').get_data(as_text=True)

    assert attr(body, 'data-steps') == 'off'


def test_the_walk_in_fields_are_always_in_the_html(shop):
    """They are hidden for a registered customer by script, not by the server.
    Rendering them conditionally would leave a no-script user unable to name a
    walk-in at all - and a debt with no name is not collectable."""
    client, _business_id, _product = shop

    assert 'name="customer_name"' in form_html(client)
    assert 'name="customer_phone"' in form_html(client)


# --- which pane opens --------------------------------------------------------

def test_a_fresh_page_opens_on_the_items(shop):
    client, _business_id, _product = shop
    body = client.get('/sales/add').get_data(as_text=True)

    assert attr(body, 'data-start-step') == '1'


def test_a_rejected_payment_field_brings_its_own_pane_back(shop):
    """The trap this page could most easily fall into. A field that failed
    validation behind a hidden pane is a page that reloads looking completely
    unchanged and says nothing about why it did not save."""
    client, _business_id, product = shop

    body = client.post('/sales/add', data={
        'sale_date': '', 'customer_id': '0',
        'items-0-product_id': str(product.id), 'items-0-quantity': '2',
        'items-0-price_at_sale': '3.00', 'settlement': 'paid',
    }).get_data(as_text=True)

    assert attr(body, 'data-start-step') == '2', \
        'the date failed on the second pane and the page opened on the first'


def test_a_rejected_item_wins_over_a_rejected_payment_field(shop):
    """Both panes can fail at once. Items come first: it is the pane the person
    was working in, and the one whose fields the other pane depends on."""
    client, _business_id, product = shop

    body = client.post('/sales/add', data={
        'sale_date': '', 'customer_id': '0',
        'items-0-product_id': str(product.id), 'items-0-quantity': '',
        'settlement': 'paid',
    }).get_data(as_text=True)

    assert attr(body, 'data-start-step') == '1'


# --- the date that was never filled in ---------------------------------------

def test_the_date_is_already_today(shop):
    """DataRequired renders `required`, so an empty date field meant the browser
    refused to submit until someone picked today by hand - on the page a shop
    uses sixty times a day, from a phone. It arrives filled in now."""
    client, _business_id, _product = shop

    assert 'value="' + date.today().isoformat() + '"' in form_html(client)


def test_the_default_date_is_not_frozen_at_import(shop):
    """`default=date.today()` would be evaluated once, when the module loads,
    and a server that stays up for a week would go on offering the day it
    started. The callable is the whole point."""
    from sales.forms import SaleForm

    field = SaleForm.sale_date.kwargs.get('default')
    assert callable(field), 'the default is a fixed date, not a function'


# --- the radio groups that replaced two dropdowns ----------------------------

def test_the_payment_choices_are_the_ones_the_server_accepts(shop):
    """Hand-written radios can drift from the SelectField's choices, and a value
    the field does not know is refused with a message nobody wrote."""
    client, _business_id, _product = shop
    from sales.forms import SaleForm

    inside = form_html(client)
    for value, _label in SaleForm().settlement.choices:
        assert f'name="settlement" value="{value}"' in inside
    for value, _label in SaleForm().payment_method.choices:
        assert f'name="payment_method" value="{value}"' in inside


def test_exactly_one_of_each_group_starts_chosen(shop):
    """Two checked radios is one bug; none is another, and that one posts
    nothing at all for the field."""
    client, _business_id, _product = shop
    inside = form_html(client)

    settlement = inside[inside.index('name="settlement"'):inside.index('name="payment_method"')]
    assert settlement.count('checked') == 1
    assert inside[inside.index('name="payment_method"'):].count('checked') == 1


def test_a_sale_posted_the_way_the_radios_post_it_is_recorded(shop):
    """End to end, with exactly the fields a browser sends from this markup."""
    client, business_id, product = shop

    response = client.post('/sales/add', data={
        'sale_date': date.today().isoformat(),
        'customer_id': '0', 'customer_name': 'Ama', 'customer_phone': '024',
        'items-0-product_id': str(product.id), 'items-0-quantity': '4',
        'items-0-price_at_sale': '3.00',
        'settlement': 'partial', 'amount_paid': '5.00',
        'payment_method': 'momo', 'payment_reference': 'MM-1',
    }, follow_redirects=True)

    assert response.status_code == 200
    sale = Sale.query.order_by(Sale.id.desc()).first()
    assert sale is not None and sale.business_id == business_id
    assert sale.customer_name == 'Ama'
    item = SaleItem.query.filter_by(sale_id=sale.id).one()
    assert item.quantity == 4
    db.session.expire_all()


# --- the two CSS decisions that fail silently ---------------------------------

def media_block(css, opener, containing):
    """The one @media block for `opener` that contains `containing`.

    Shared shape with the helper in test_navigation. It ends at the matching
    brace so a later rule cannot answer for this one, and it finds its block by
    content because there are several blocks per breakpoint and their order is
    whatever the file happens to be in today.
    """
    import re as _re

    found = []
    for m in _re.finditer(_re.escape(opener), css):
        depth, j = 0, css.index('{', m.start())
        for k in range(j, len(css)):
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
                if depth == 0:
                    found.append(css[m.start():k + 1])
                    break
        else:
            raise AssertionError(f'{opener} is never closed')

    matched = [b for b in found if containing in b]
    assert len(matched) == 1, (
        f'{len(matched)} of the {len(found)} {opener} blocks contain '
        f'{containing!r}; expected exactly one')
    return matched[0]


def test_the_running_total_sits_on_the_tab_bar_not_under_it(shop):
    """On a phone the total sticks to the bottom of the screen, and the tab bar
    is already fixed there. The offset has to be *derived* from the bar's own
    height - a literal drifts the moment the bar changes, and the failure is a
    Record sale button sitting behind a row of tabs."""
    client, _business_id, _product = shop
    css = client.get('/static/css/style.css').get_data(as_text=True)

    phone = media_block(css, '@media (max-width: 767.98px)', containing='.sale-summary {')
    rule = phone[phone.index('.sale-summary {'):]
    rule = rule[:rule.index('}')]

    assert 'var(--phone-tabs-h)' in rule, 'the offset is a literal, not the bar height'
    assert 'safe-area-inset-bottom' in rule, 'nothing clears the iOS home indicator'


def test_a_chosen_chip_does_not_depend_on_has(shop):
    """`:has()` is the obvious way to style a label from its checked radio, and
    it is unsupported on the older Android WebViews this is sold into. The
    failure would be silent and total - no chip would ever look chosen, on the
    control that says whether a sale was paid for."""
    client, _business_id, _product = shop
    css = client.get('/static/css/style.css').get_data(as_text=True)

    import re as _re

    live = _re.sub(r'/\*.*?\*/', '', css, flags=_re.S)
    chip_rules = [line for line in live.splitlines()
                  if '.chip' in line and ':has(' in line]
    assert not chip_rules, f'chips rely on :has(): {chip_rules}'
    assert '.chip input:checked + span' in css, 'nothing marks the chosen chip at all'
