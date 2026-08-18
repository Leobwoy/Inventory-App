"""The dashboard — Phase C2 of the redesign, done late.

This page was skipped by mistake when the sale form was rebuilt, so it stayed on
the old layout for two commits longer than it should have.

Four numbers, then the trend and what needs doing. The right-hand panel is
**Needs attention**, not an activity feed: the only source for a feed is the
audit log, which is an `advanced`-tier feature, so on Kiosk, Shop and Depot the
panel would open empty and stay empty forever. Needs attention is derived from
stock, expiry and debt, is already permission-filtered, and empties itself.

What is asserted here is what would break quietly: that a number nobody may see
is not shown, that the alerts on this page are the same ones the nav badge
counts, and that the chart does not go back to having the dark theme's colours
written into it.
"""
import re

import pytest

from billing.models import Plan, Subscription
from extensions import db


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    return client, business_id


def body(client):
    response = client.get('/')
    assert response.status_code == 200
    return response.get_data(as_text=True)


# --- the four numbers --------------------------------------------------------

def test_every_stat_goes_somewhere(shop):
    """A number you cannot act on is a number you stop reading. Each cell is a
    link to the page that explains it."""
    client, _business_id = shop
    page = body(client)

    cells = re.findall(r'<a class="stat-cell" href="([^"]+)"', page)
    assert len(cells) >= 3, f'only {len(cells)} stat cells are links'
    assert '/products/low-stock' in cells
    assert '/products/' in cells


def test_the_week_is_compared_with_the_one_before(shop, make_product):
    """The old page showed a total with nothing to judge it against. A number on
    its own does not tell a shopkeeper whether trade is up.

    A sale is recorded first, deliberately. The comparison and the "nothing sold
    yet" fallback are two branches, and an `or` across both passes when either
    renders - which is how this test first stayed green with the comparison
    deleted."""
    import datetime

    client, business_id = shop
    product = make_product(business_id, sku='CMP-1', stock=50)
    client.post('/sales/add', data={
        'sale_date': datetime.date.today().isoformat(), 'customer_id': '0',
        'items-0-product_id': str(product.id), 'items-0-quantity': '2',
        'items-0-price_at_sale': '3.00', 'settlement': 'paid',
    }, follow_redirects=True)

    page = body(client)

    assert 'nothing sold yet' not in page, 'the fixture recorded no sale'
    assert 'on last week' in page


def test_a_quiet_week_is_not_coloured_like_a_failure(shop):
    """Down is information, not an error. Colouring it red teaches people to
    dread opening the page they are meant to check every morning."""
    client, _business_id = shop
    css = client.get('/static/css/style.css').get_data(as_text=True)

    rule = css[css.index('.stat-delta.is-down {'):]
    rule = rule[:rule.index('}')]
    assert 'danger' not in rule, 'a slower week renders as an error'


# --- money owed is gated twice ----------------------------------------------

def test_money_owed_is_hidden_without_the_feature(shop):
    """The credit ledger is a paid feature. On the free plan the card would be a
    permanent zero advertising something they have not bought."""
    client, business_id = shop
    free = Plan.query.filter_by(code='free').first()
    Subscription.query.filter_by(business_id=business_id).update({'plan_id': free.id})
    db.session.commit()

    assert 'Owed to you' not in body(client)


def test_money_owed_is_hidden_without_the_permission(register, make_staff):
    """Seeing what customers owe is its own permission.

    Permissions set explicitly rather than by role: the Sales Staff preset
    *does* include `credit.view`, because they are the people who take the
    payments. Someone who may ring up a sale but not read the debt book is the
    case this guards, and naming the permissions says so."""
    client, business_id = register()
    staff_client = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                              permissions={'products.view', 'sales.view',
                                           'sales.create'})

    assert 'Owed to you' not in staff_client.get('/').get_data(as_text=True)


def test_money_owed_shows_for_an_owner(shop):
    client, _business_id = shop
    assert 'Owed to you' in body(client)


# --- needs attention ---------------------------------------------------------

def test_the_panel_is_needs_attention_and_not_a_feed(shop):
    """Recorded as a decision, not a preference. An activity feed can only come
    from the audit log, which is `advanced`-tier - so three of the four plans
    would open this page to an empty panel every day."""
    client, _business_id = shop
    page = body(client)

    assert 'Needs attention' in page
    assert 'salesChart' in page


def test_an_alert_reaches_the_dashboard(shop, make_product):
    """The same list the nav badge counts, through the same per-request cache,
    so the two cannot drift."""
    client, business_id = shop
    product = make_product(business_id, sku='OUT-1', name='Club Beer 330ml', stock=0)
    product.min_stock_alert = 10
    db.session.commit()

    page = body(client)

    assert 'out of stock' in page.lower()
    assert 'Nothing needs you right now' not in page


def test_it_says_so_when_there_is_nothing_to_do(shop):
    """An empty panel with no words is indistinguishable from a broken one."""
    client, _business_id = shop
    assert 'Nothing needs you right now' in body(client)


def test_the_panel_links_to_the_whole_list(shop, make_product):
    client, business_id = shop
    product = make_product(business_id, sku='OUT-2', name='Malta 330ml', stock=0)
    product.min_stock_alert = 10
    db.session.commit()

    assert '/products/alerts' in body(client)


# --- the chart ---------------------------------------------------------------

def test_the_chart_reads_the_theme_rather_than_hardcoding_it(shop):
    """Chart.js paints to a canvas, so it cannot inherit a CSS variable the way
    the rest of the page does - it had eight colours written into it, every one
    of them the dark theme's. Someone on the light theme got a chart drawn for a
    background that was not there."""
    client, _business_id = shop
    page = body(client)

    script = page[page.index('salesChart'):]
    assert 'getPropertyValue' in script, 'the chart no longer reads any token'
    assert '--accent-primary' in script

    # A colour may appear only as a fallback inside `token(name, fallback)` -
    # never as a value handed straight to Chart.js. Asserting the literals are
    # simply absent was wrong: the fallbacks are deliberate, for the case where
    # a token has been renamed out from under this file.
    chart = script[:script.index('MutationObserver')]
    for literal in re.findall(r"'(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))'", chart):
        assert re.search(r"token\([^)]*'" + re.escape(literal) + r"'\s*\)", chart), (
            f'{literal} is handed to the chart directly rather than as a token '
            'fallback, so it will not follow the theme')


def test_the_chart_is_redrawn_when_the_theme_changes(shop):
    """Reading the tokens once at load is only half of it: the sidebar toggle
    changes the theme without reloading, and a canvas does not repaint itself."""
    client, _business_id = shop
    page = body(client)

    # Scoped to the chart's own <script>, not to the end of the document.
    # base.html carries a `tracktrack:theme` listener of its own for the
    # sidebar toggle's icon, and a slice running past it kept this assertion
    # green with the chart's listener deleted.
    head = page.index('sales-trend-labels')
    raw = page[head:page.index('</script>', page.index('<script>', head))]
    while '/*' in raw and '*/' in raw[raw.index('/*'):]:
        a = raw.index('/*')
        raw = raw[:a] + raw[raw.index('*/', a) + 2:]
    script = ' '.join(l for l in raw.splitlines()
                      if not l.strip().startswith('//'))
    assert 'tracktrack:theme' in script, 'the device-change event is not listened for'
    assert 'MutationObserver' in script, (
        'nothing notices the sidebar toggle, which rewrites the attribute '
        'directly rather than firing the event')


# --- the target size that was scoped to one page ----------------------------

def test_every_button_is_thumb_sized_on_a_phone(shop):
    """It was scoped to `.sale-form` when first measured there. The dashboard's
    own "Record a sale" then came out at 33px, because a page-header rule shrinks
    buttons on a phone and overrides `.btn-lg` completely. The rule is not per
    page."""
    client, _business_id = shop
    css = client.get('/static/css/style.css').get_data(as_text=True)

    phone = css[css.index('@media (max-width: 767.98px)'):]
    m = re.search(r'^\s{2}\.btn\s*\{([^}]*)\}', phone, re.M)
    assert m, 'no app-wide button rule in the phone block'
    assert 'min-height: 44px' in m.group(1)
