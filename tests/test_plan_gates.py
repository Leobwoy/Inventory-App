"""The features a plan advertises are the features it actually gates.

`billing/plans.py` declares fourteen feature codes. Seven of them were checked
nowhere: a Kiosk account could export to Excel and PDF, read the alerts inbox,
and get expiry warnings - all of which the price list sells as paid.

Three of the seven stay ungated on purpose, because the thing they name does not
exist yet: `supplier_scorecards` (Stage 2.6), `margin_reports` (there is no
profit report - `cost_price` is read by pricing and the catalogue export and
nothing else) and `api_access` (there is no public API; the offline sync
endpoints are gated on `offline`). Gating a capability that has not been built
would be advertising by decorator.

The remaining four are here. Note which gate is which: `reports.export` asks
whether this *person* may take data out of the building, and the plan asks
whether this *business* paid for the format. Both apply and neither implies the
other, which is the distinction `billing/plans.py` opens by making.
"""
import datetime
import re

import pytest

from billing.models import Plan, Subscription
from billing.plans import FEATURES, features_for_tier
from extensions import db

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml', stock=5)
    return client, business_id, product


def on_plan(business_id, code):
    """Put the business on a real, paid, unexpired plan.

    Status alone is not enough - `effective_plan` reads `paid_through` and falls
    back to Free without it, so a test that sets only the status is testing the
    Free plan by accident.
    """
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code=code).one().id
    subscription.status = 'active'
    subscription.paid_through = TODAY + datetime.timedelta(days=30)
    db.session.commit()


# --- the catalogue itself ----------------------------------------------------

def test_every_declared_feature_is_reachable_from_some_plan(shop):
    """A code with a tier nothing sells is a feature nobody can ever buy."""
    sellable = features_for_tier('custom')
    assert set(FEATURES) == sellable


def test_the_tiers_stack(shop):
    """Each plan includes everything below it, which is what lets a gate name
    one code rather than a list of plans."""
    assert features_for_tier('basic') < features_for_tier('standard')
    assert features_for_tier('standard') < features_for_tier('advanced')
    assert 'purchase_orders' in features_for_tier('advanced')


# --- exports: two formats, two tiers -----------------------------------------

@pytest.mark.parametrize('fmt', ['csv', 'excel', 'pdf'])
def test_the_free_plan_cannot_export_a_report_at_all(shop, fmt):
    client, business_id, _product = shop
    on_plan(business_id, 'free')

    response = client.get('/reports/stock?export=%s' % fmt, follow_redirects=True)

    assert response.status_code == 200
    assert 'text/html' in response.content_type, 'a file came back on the free plan'
    assert 'not included in your current plan' in response.get_data(as_text=True)


def test_shop_gets_csv_but_not_excel_or_pdf(shop):
    """The line the price list draws: CSV on Shop, the rest on Depot."""
    client, business_id, _product = shop
    on_plan(business_id, 'basic')

    csv_response = client.get('/reports/stock?export=csv')
    assert 'text/csv' in csv_response.content_type

    for fmt in ('excel', 'pdf'):
        blocked = client.get('/reports/stock?export=%s' % fmt, follow_redirects=True)
        assert 'text/html' in blocked.content_type, fmt
        assert 'Export to Excel and PDF' in blocked.get_data(as_text=True)


def test_depot_gets_every_format(shop):
    client, business_id, _product = shop
    on_plan(business_id, 'standard')

    assert 'text/csv' in client.get('/reports/stock?export=csv').content_type
    assert 'spreadsheet' in client.get('/reports/stock?export=excel').content_type
    assert 'pdf' in client.get('/reports/stock?export=pdf').content_type


def test_a_refused_export_still_shows_the_report(shop):
    """Reading the report is free; only taking it away costs money. Redirecting
    somebody off a page they are entitled to read would be a strange way to say
    a button costs extra - so this flashes and renders, exactly as the
    permission check already did."""
    client, business_id, _product = shop
    on_plan(business_id, 'free')

    page = client.get('/reports/stock?export=excel',
                      follow_redirects=True).get_data(as_text=True)

    # Anchored to the report's own heading, not just the product name: the
    # dashboard lists the same product, so a redirect to it passed this check.
    # Caught by falsification.
    assert 'Stock Level Report' in page, 'the report itself was taken away too'
    assert 'BelAqua 750ml' in page


def test_the_catalogue_export_obeys_the_same_two_tiers(shop):
    """Same rule on the product list's bulk export. Unlike a report page there
    is nothing to fall back to rendering, so it returns to the list."""
    client, business_id, product = shop
    on_plan(business_id, 'basic')

    allowed = client.post('/products/bulk_action', data={
        'action': 'export_csv', 'product_ids': [str(product.id)]})
    assert 'text/csv' in allowed.content_type

    blocked = client.post('/products/bulk_action', data={
        'action': 'export_excel', 'product_ids': [str(product.id)],
    }, follow_redirects=True)
    assert 'text/html' in blocked.content_type
    assert 'Export to Excel and PDF' in blocked.get_data(as_text=True)


# --- the alerts inbox --------------------------------------------------------

def test_the_alerts_inbox_is_a_paid_page(shop):
    client, business_id, _product = shop
    on_plan(business_id, 'basic')

    page = client.get('/products/alerts', follow_redirects=True)

    assert 'Alerts inbox' in page.get_data(as_text=True)


def test_the_badge_is_gated_with_the_page_it_counts(shop):
    """Otherwise the sidebar advertises a number that opens onto a redirect.

    Matched as an element: the guided tour's step list names `#nav-alerts` as an
    anchor, so a substring check finds it in the tour config on every plan. The
    tour is unaffected either way - `static/js/tour.js` keeps only the steps
    whose anchor is actually on the page, which is why hiding a nav link drops
    its step instead of leaving an empty bubble.
    """
    client, business_id, _product = shop
    on_plan(business_id, 'basic')

    assert client.get('/products/alerts/count',
                      follow_redirects=True).status_code == 200
    assert not re.search(r'<a[^>]*id="nav-alerts"', client.get('/').get_data(as_text=True))


def test_the_dashboard_does_not_claim_all_is_well_when_it_cannot_tell(shop):
    """The empty state read "Nothing needs you right now - stock, expiry dates
    and debts are all where they should be". With the inbox gated, `alerts` is
    empty for a reason that has nothing to do with the shop being fine, and this
    one is out of stock."""
    client, business_id, product = shop
    on_plan(business_id, 'basic')
    product.quantity_in_stock = 0
    db.session.commit()

    page = client.get('/').get_data(as_text=True)

    assert 'Nothing needs you right now' not in page
    assert 'Alerts are not on your plan' in page


def test_depot_sees_the_inbox(shop):
    client, business_id, product = shop
    on_plan(business_id, 'standard')
    product.quantity_in_stock = 0
    db.session.commit()

    assert client.get('/products/alerts').status_code == 200
    assert re.search(r'<a[^>]*id="nav-alerts"', client.get('/').get_data(as_text=True))


# --- expiry: the alerts are paid for, the tracking underneath is not ---------

def test_expiry_warnings_need_the_plan(shop, make_product):
    from products.models import ItemGroup
    from services import notifications

    client, business_id, _product = shop
    make_product(business_id, sku='MILK-1', name='Fresh Milk', stock=20,
                 expiry=TODAY - datetime.timedelta(days=1))
    # The item group has to opt in as well - `track_expiry` is off by default,
    # because most of what this market sells does not meaningfully expire and
    # warning about all of it teaches people to ignore warnings.
    ItemGroup.query.filter_by(business_id=business_id).one().track_expiry = True
    db.session.commit()
    on_plan(business_id, 'standard')
    assert any(a['kind'] == 'expired' for a in notifications.for_business(business_id))

    on_plan(business_id, 'basic')
    kinds = {a['kind'] for a in notifications.for_business(business_id)}
    assert 'expired' not in kinds
    assert 'expiring' not in kinds


def test_stock_warnings_are_not_expiry_warnings(shop):
    """Low stock and out of stock stay in the list on every plan that has the
    inbox at all. They are what the inbox is *for*; expiry is the extra."""
    from services import notifications

    client, business_id, product = shop
    on_plan(business_id, 'basic')
    product.quantity_in_stock = 0
    db.session.commit()

    kinds = {a['kind'] for a in notifications.for_business(business_id)}
    assert 'out_of_stock' in kinds


def test_the_tracking_underneath_expiry_alerts_is_never_switched_off(shop, make_product):
    """FEFO picks stock by expiry date. Gating the *tracking* rather than the
    alerts would change which bottle leaves the shelf on a cheaper plan, which
    is a correctness change dressed as a billing one."""
    from services import stock

    client, business_id, _product = shop
    on_plan(business_id, 'basic')
    perishable = make_product(business_id, sku='MILK-1', name='Fresh Milk', stock=20,
                              expiry=TODAY + datetime.timedelta(days=2))

    stock.deduct_fefo(perishable, 5, business_id)
    db.session.commit()

    from purchases.models import StockBatch
    batch = StockBatch.query.filter_by(product_id=perishable.id).one()
    assert batch.quantity_remaining == 15, 'FEFO stopped working on a cheaper plan'
    assert batch.expiry_date is not None, 'the expiry date was not recorded'
