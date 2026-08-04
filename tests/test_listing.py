"""Search, sort and filter on the record lists.

Sales had a bulk-action dropdown and pagination but no way to find anything: a
wholesaler doing 60 sales a day fills fifteen pages in a week, and the only
route to a particular one was paging through. Products had a search box, the
audit log had filters, and nothing else had either.

The two rules worth testing are that a filter genuinely narrows the whole table
rather than the visible page, and that a sort key arriving in the query string
cannot reach the database unrecognised.
"""
import datetime
from decimal import Decimal

import pytest

from extensions import db
from products.models import Product, Supplier
from sales.models import Customer, Sale

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    client, business_id = register()
    product = make_product(business_id, sku='BA-750', name='BelAqua 750ml',
                           unit_price='10.00', cost_price='6.00', stock=5000)
    other = make_product(business_id, sku='CB-625', name='Club Beer 625ml',
                         unit_price='12.00', cost_price='8.00', stock=10)
    return client, business_id, product, other


def sell(client, product, quantity=1, customer_id='0', customer_name='',
         settlement='credit', paid='0'):
    client.post('/sales/add', data={
        'sale_date': TODAY.isoformat(), 'customer_id': customer_id,
        'customer_name': customer_name, 'customer_phone': '',
        'items-0-product_id': str(product.id),
        'items-0-quantity': str(quantity),
        'items-0-price_at_sale': str(product.unit_price),
        'settlement': settlement, 'payment_method': 'cash',
        'payment_reference': '', 'amount_paid': paid,
    }, follow_redirects=True)


# --- searching -------------------------------------------------------------

def test_searching_sales_by_buyer_finds_both_kinds_of_buyer(shop):
    """A sale's buyer is a customer record or a name typed on the form. Searching
    only one of them misses half the sales."""
    client, business_id, product, _other = shop
    customer = Customer(business_id=business_id, name='Madina Provisions')
    db.session.add(customer)
    db.session.commit()
    sell(client, product, customer_id=str(customer.id))
    sell(client, product, customer_name='Kojo at Circle')

    assert b'Madina Provisions' in client.get('/sales/?q=madina').data
    assert b'Kojo at Circle' not in client.get('/sales/?q=madina').data
    assert b'Kojo at Circle' in client.get('/sales/?q=kojo').data


def test_searching_sales_by_invoice_number(shop):
    """It is the number printed on the copy the customer brings back."""
    client, _business_id, product, _other = shop
    sell(client, product, customer_name='Kojo at Circle')
    sale = Sale.query.one()

    assert client.get(f'/sales/?q={sale.id}').status_code == 200
    assert b'Kojo at Circle' in client.get(f'/sales/?q=%23{sale.id}').data


def test_search_matches_the_middle_of_a_name_not_only_the_start(shop):
    """Users search for the word they remember, which is rarely the first one."""
    client, _business_id, _product, _other = shop
    assert b'BelAqua 750ml' in client.get('/products/?q=aqua').data


def test_a_search_reports_how_many_matched_not_how_many_fit_on_a_page(shop):
    """Showing the page length makes every search read '15'."""
    client, _business_id, product, _other = shop
    for _ in range(3):
        sell(client, product, customer_name='Kojo at Circle')

    body = client.get('/sales/?q=kojo').get_data(as_text=True)
    assert '3 records' in body


# --- filtering -------------------------------------------------------------

def test_filtering_sales_by_settlement_narrows_the_whole_table(shop):
    """The filter runs in the database, not over the current page - otherwise it
    would only ever hide rows you could already see."""
    client, _business_id, product, _other = shop
    sell(client, product, quantity=1, settlement='paid', customer_name='Paid Pete')
    sell(client, product, quantity=1, settlement='credit', customer_name='Owing Ofori')
    sell(client, product, quantity=2, settlement='partial', paid='5.00',
         customer_name='Half Hannah')

    paid = client.get('/sales/?settlement=paid').get_data(as_text=True)
    assert 'Paid Pete' in paid
    assert 'Owing Ofori' not in paid and 'Half Hannah' not in paid

    unpaid = client.get('/sales/?settlement=credit').get_data(as_text=True)
    assert 'Owing Ofori' in unpaid and 'Paid Pete' not in unpaid

    part = client.get('/sales/?settlement=partial').get_data(as_text=True)
    assert 'Half Hannah' in part and 'Paid Pete' not in part


def test_filtering_products_by_stock_level(shop):
    """The reorder list is the whole point of a stock filter."""
    client, business_id, _product, other = shop
    other.min_stock_alert = 50           # 10 in stock, so below the threshold
    db.session.commit()

    low = client.get('/products/?stock=low').get_data(as_text=True)
    assert 'Club Beer 625ml' in low
    assert 'BelAqua 750ml' not in low


def test_filtering_products_by_status_uses_active_not_deleted(shop):
    client, _business_id, _product, other = shop
    other.is_active = False
    db.session.commit()

    assert 'Club Beer' not in client.get('/products/?status=active').get_data(as_text=True)
    assert 'Club Beer' in client.get('/products/?status=inactive').get_data(as_text=True)


def test_search_and_filter_and_sort_compose(shop):
    """Each works alone; the combination is what breaks when they are bolted on
    separately."""
    client, _business_id, product, _other = shop
    sell(client, product, quantity=1, settlement='paid', customer_name='Kojo at Circle')
    sell(client, product, quantity=1, settlement='credit', customer_name='Kojo at Circle')
    sell(client, product, quantity=1, settlement='credit', customer_name='Ama at Kaneshie')

    body = client.get('/sales/?q=kojo&settlement=credit&sort=oldest').get_data(as_text=True)
    assert '1 record' in body
    assert 'Ama at Kaneshie' not in body


# --- sorting ---------------------------------------------------------------

def test_sorting_products_by_price(shop):
    client, _business_id, _product, _other = shop
    low = client.get('/products/?sort=price_low').get_data(as_text=True)
    high = client.get('/products/?sort=price_high').get_data(as_text=True)

    assert low.index('BelAqua') < low.index('Club Beer')     # 10.00 then 12.00
    assert high.index('Club Beer') < high.index('BelAqua')


def test_sorting_sales_oldest_first_reverses_the_default(shop):
    client, _business_id, product, _other = shop
    sell(client, product, customer_name='First Felix')
    sale = Sale.query.one()
    sale.sale_date = TODAY - datetime.timedelta(days=10)
    db.session.commit()
    sell(client, product, customer_name='Later Larry')

    newest = client.get('/sales/').get_data(as_text=True)
    oldest = client.get('/sales/?sort=oldest').get_data(as_text=True)
    assert newest.index('Later Larry') < newest.index('First Felix')
    assert oldest.index('First Felix') < oldest.index('Later Larry')


def test_an_unknown_sort_key_falls_back_instead_of_reaching_the_database(shop):
    """A sort column from the query string is user input. Whitelisting means a
    junk or hostile key becomes the default rather than an error or an
    injection point."""
    client, _business_id, product, _other = shop
    sell(client, product, customer_name='Kojo at Circle')

    for key in ('nonsense', 'id; DROP TABLE sale', '(SELECT 1)'):
        response = client.get(f'/sales/?sort={key}')
        assert response.status_code == 200
        assert b'Kojo at Circle' in response.data
    assert Sale.query.count() == 1


def test_an_unknown_filter_value_is_ignored(shop):
    client, _business_id, product, _other = shop
    sell(client, product, settlement='paid', customer_name='Paid Pete')

    assert b'Paid Pete' in client.get('/sales/?settlement=nonsense').data


# --- keeping context -------------------------------------------------------

def test_paging_keeps_the_search(shop):
    """Page 2 of a search has to still be the search, or the filter silently
    resets the moment the results do not fit on one page."""
    client, _business_id, product, _other = shop
    for _ in range(20):
        sell(client, product, customer_name='Kojo at Circle')
    sell(client, product, customer_name='Ama at Kaneshie')

    body = client.get('/sales/?q=kojo').get_data(as_text=True)
    assert 'q=kojo' in body, 'pagination links dropped the search'

    page_two = client.get('/sales/?q=kojo&page=2').get_data(as_text=True)
    assert 'Ama at Kaneshie' not in page_two


def test_an_empty_result_offers_a_way_back(shop):
    client, _business_id, product, _other = shop
    sell(client, product, customer_name='Kojo at Circle')

    body = client.get('/sales/?q=nobodyhere').get_data(as_text=True)
    assert 'No sale matches that search' in body
    assert 'Clear filters' in body


# --- the other lists -------------------------------------------------------

def test_customers_and_suppliers_are_searchable(shop):
    client, business_id, _product, _other = shop
    db.session.add_all([
        Customer(business_id=business_id, name='Madina Provisions', phone='0244000111'),
        Customer(business_id=business_id, name='Kaneshie Superstore', phone='0208899001'),
        Supplier(business_id=business_id, name='Voltic Ghana', phone='0244112233'),
        Supplier(business_id=business_id, name='Accra Bulk Beverages', phone='0201445566'),
    ])
    db.session.commit()

    customers = client.get('/sales/customers?q=madina').get_data(as_text=True)
    assert 'Madina Provisions' in customers and 'Kaneshie Superstore' not in customers

    # By phone too - it is how a wholesaler identifies a caller.
    by_phone = client.get('/sales/customers?q=0208899').get_data(as_text=True)
    assert 'Kaneshie Superstore' in by_phone

    suppliers = client.get('/products/suppliers?q=voltic').get_data(as_text=True)
    assert 'Voltic Ghana' in suppliers and 'Accra Bulk Beverages' not in suppliers


def test_purchase_orders_are_searchable_by_supplier(shop, make_po):
    client, business_id, product, _other = shop
    supplier = Supplier(business_id=business_id, name='Voltic Ghana')
    db.session.add(supplier)
    db.session.commit()
    po, _item = make_po(business_id, product)
    po.supplier_id = supplier.id
    db.session.commit()

    assert b'Voltic Ghana' in client.get('/purchases/?q=voltic').data


def test_a_purchase_order_without_a_supplier_still_lists(shop, make_po):
    """An outer join, not an inner one: sorting or searching must not quietly
    drop orders that have no supplier attached."""
    client, business_id, product, _other = shop
    po, _item = make_po(business_id, product)
    po.supplier_id = None
    db.session.commit()

    assert client.get('/purchases/?sort=supplier').status_code == 200
    assert f'#{po.id}' in client.get('/purchases/?sort=supplier').get_data(as_text=True) \
        or str(po.id) in client.get('/purchases/?sort=supplier').get_data(as_text=True)


def test_lists_stay_inside_the_business(shop, register, make_product):
    """Search is a new way to reach rows, so it is a new way to leak them."""
    client, _business_id, _product, _other = shop
    other_client, other_id = register(name='Kumasi Drinks', email='owner@kd.example.com')
    make_product(other_id, sku='KD-1', name='Kumasi Special Water')

    assert b'Kumasi Special Water' not in client.get('/products/?q=kumasi').data
    assert b'BelAqua' not in other_client.get('/products/?q=belaqua').data
