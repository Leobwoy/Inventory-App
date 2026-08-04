"""Customer credit book — Stage 2.2.

Wholesale runs on trade credit and the application recorded every sale as though
it were settled, so "who owes me money" - the question its users ask most often -
was the one it could not answer.

Balances are derived from sales minus payments on every read, never stored. These
tests exist mainly to keep that arithmetic honest.
"""
import datetime
from decimal import Decimal

import pytest

from auth.models import AuditLog
from billing.models import Plan, Subscription
from credit.models import Payment, sale_balance, sale_paid, sale_total, settlement_status
from extensions import db
from sales.models import Customer, Sale
from services import credit

TODAY = datetime.date.today()


@pytest.fixture
def shop(register, make_product):
    """A business with stock and one named customer."""
    client, business_id = register()
    product = make_product(business_id, unit_price='100.00', cost_price='60.00', stock=1000)
    customer = Customer(business_id=business_id, name='Madina Provisions', phone='0244000111')
    db.session.add(customer)
    db.session.commit()
    return client, business_id, product, customer


def sell(client, product, customer, quantity=8, settlement='credit', paid=None,
         method='momo', reference=None, when=None):
    """Record a sale, returning the Sale."""
    data = {
        'sale_date': (when or TODAY).isoformat(),
        'customer_id': str(customer.id) if customer else '0',
        'customer_name': '',
        'items-0-product_id': str(product.id),
        'items-0-quantity': str(quantity),
        'items-0-price_at_sale': '100.00',
        'settlement': settlement,
        'payment_method': method,
        'payment_reference': reference or '',
    }
    if paid is not None:
        data['amount_paid'] = str(paid)
    client.post('/sales/add', data=data, follow_redirects=True)
    return Sale.query.order_by(Sale.id.desc()).first()


# ------------------------------------------------------------------- the maths

def test_a_credit_sale_owes_the_whole_amount(shop):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)      # 8 x 100

    assert sale_total(sale) == Decimal('800.00')
    assert sale_paid(sale) == Decimal('0')
    assert sale_balance(sale) == Decimal('800.00')
    assert settlement_status(sale) == 'credit'


def test_a_paid_sale_owes_nothing(shop):
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8, settlement='paid')

    assert sale_paid(sale) == Decimal('800.00')
    assert sale_balance(sale) == Decimal('0')
    assert settlement_status(sale) == 'paid'


def test_a_part_payment_leaves_the_remainder(shop):
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8, settlement='partial', paid='300.00')

    assert sale_paid(sale) == Decimal('300.00')
    assert sale_balance(sale) == Decimal('500.00')
    assert settlement_status(sale) == 'partial'


def test_the_payment_records_how_the_money_arrived(shop):
    """The MoMo reference is how this market reconciles."""
    client, _business_id, product, customer = shop
    sell(client, product, customer, settlement='paid', method='momo', reference='MP240801.1234')

    payment = Payment.query.one()
    assert payment.method == 'momo'
    assert payment.reference == 'MP240801.1234'
    assert payment.recorded_by is not None
    assert payment.customer_id == customer.id


def test_successive_payments_settle_the_sale(shop):
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)       # 800 on credit

    for amount in ('300.00', '200.00', '300.00'):
        client.post(f'/credit/sale/{sale.id}/pay', data={
            'amount': amount, 'method': 'momo', 'reference': '',
            'paid_on': TODAY.isoformat(), 'notes': '',
        }, follow_redirects=True)

    assert sale_paid(sale) == Decimal('800.00')
    assert sale_balance(sale) == Decimal('0')
    assert settlement_status(sale) == 'paid'


def test_overpayment_is_refused(shop):
    """Accepting more than is owed would read as a negative debt on the ageing
    report, with nothing to apply the excess to."""
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)

    response = client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '900.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    assert 'more than the 800.00 outstanding' in response.get_data(as_text=True)
    assert Payment.query.count() == 0


def test_a_future_dated_payment_is_refused(shop):
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer)

    response = client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '100.00', 'method': 'cash', 'reference': '',
        'paid_on': (TODAY + datetime.timedelta(days=1)).isoformat(), 'notes': '',
    }, follow_redirects=True)

    assert 'cannot be dated in the future' in response.get_data(as_text=True)
    assert Payment.query.count() == 0


def test_a_part_payment_larger_than_the_sale_is_capped(shop):
    """Typing 5000 against an 800 sale must not create a negative balance."""
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8, settlement='partial', paid='5000.00')

    assert sale_paid(sale) == Decimal('800.00')
    assert sale_balance(sale) == Decimal('0')


# ----------------------------------------------------------------- the balance

def test_customer_balance_spans_several_sales(shop):
    client, business_id, product, customer = shop
    sell(client, product, customer, quantity=8)                              # 800
    sell(client, product, customer, quantity=2, settlement='partial', paid='50.00')   # 200-50
    sell(client, product, customer, quantity=1, settlement='paid')           # settled

    assert credit.customer_balance(business_id, customer.id) == Decimal('950.00')
    assert credit.total_outstanding(business_id) == Decimal('950.00')


def test_settled_sales_drop_off_the_outstanding_list(shop):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)
    assert len(credit.outstanding_sales(business_id)) == 1

    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '800.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    assert credit.outstanding_sales(business_id) == []
    assert credit.total_outstanding(business_id) == Decimal('0')


def test_walk_in_credit_is_still_owed(shop):
    """Money owed by someone with no customer record is still money owed."""
    client, business_id, product, _customer = shop
    sell(client, product, None, quantity=3)

    assert credit.total_outstanding(business_id) == Decimal('300.00')
    rows = credit.ageing(business_id)
    assert len(rows) == 1
    assert rows[0]['customer'] is None


# ------------------------------------------------------------------- ageing

@pytest.mark.parametrize('days_ago,expected', [
    (0, 'Current'), (30, 'Current'),
    (31, '31-60 days'), (60, '31-60 days'),
    (61, '61-90 days'), (90, '61-90 days'),
    (91, 'Over 90 days'), (400, 'Over 90 days'),
])
def test_debts_land_in_the_right_bucket(shop, days_ago, expected):
    client, business_id, product, customer = shop
    sell(client, product, customer, quantity=1,
         when=TODAY - datetime.timedelta(days=days_ago))

    row = credit.ageing(business_id)[0]
    assert row['buckets'][expected] == Decimal('100.00')
    assert row['oldest_days'] == days_ago


def test_ageing_lists_the_biggest_debt_first(shop, make_product):
    """The order a wholesaler wants to make calls in."""
    client, business_id, product, small = shop
    big = Customer(business_id=business_id, name='Kaneshie Superstore')
    db.session.add(big)
    db.session.commit()

    sell(client, product, small, quantity=2)      # 200
    sell(client, product, big, quantity=9)        # 900

    rows = credit.ageing(business_id)
    assert [r['customer'].name for r in rows] == ['Kaneshie Superstore', 'Madina Provisions']


def test_bucket_totals_add_up(shop):
    client, business_id, product, customer = shop
    sell(client, product, customer, quantity=1, when=TODAY)
    sell(client, product, customer, quantity=2, when=TODAY - datetime.timedelta(days=45))

    totals = credit.bucket_totals(credit.ageing(business_id))
    assert totals['Current'] == Decimal('100.00')
    assert totals['31-60 days'] == Decimal('200.00')
    assert sum(totals.values()) == credit.total_outstanding(business_id)


# ----------------------------------------------------------------- statement

def test_statement_runs_a_balance_in_order(shop):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8,
                when=TODAY - datetime.timedelta(days=10))
    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '300.00', 'method': 'momo', 'reference': 'MP-1',
        'paid_on': (TODAY - datetime.timedelta(days=5)).isoformat(), 'notes': '',
    }, follow_redirects=True)

    events = credit.statement(business_id, customer.id)
    assert [e['kind'] for e in events] == ['sale', 'payment']
    assert events[0]['balance'] == Decimal('800.00')
    assert events[1]['balance'] == Decimal('500.00')
    assert events[1]['ref'] == 'MP-1'


def test_a_same_day_payment_sorts_after_its_sale(shop):
    """Otherwise the running balance dips negative before the sale appears."""
    client, business_id, product, customer = shop
    sell(client, product, customer, quantity=8, settlement='paid')

    events = credit.statement(business_id, customer.id)
    assert [e['kind'] for e in events] == ['sale', 'payment']
    assert all(e['balance'] >= 0 for e in events)


# --------------------------------------------------------------- reversal

def test_reversing_a_payment_restores_the_balance(shop):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8, settlement='partial', paid='300.00')
    payment = Payment.query.one()

    client.post(f'/credit/payment/{payment.id}/delete', follow_redirects=True)

    assert Payment.query.count() == 0
    assert sale_balance(sale) == Decimal('800.00')
    assert 'payment.delete' in [e.action for e in AuditLog.query.all()]


def test_voiding_a_sale_takes_its_payments_with_it(shop):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8, settlement='partial', paid='300.00')
    assert Payment.query.count() == 1

    client.post('/sales/bulk_action', data={'action': 'delete', 'sale_ids': [str(sale.id)]},
                follow_redirects=True)

    assert Payment.query.count() == 0
    assert credit.total_outstanding(business_id) == Decimal('0')


# ------------------------------------------------------------------- gating

def test_credit_is_a_paid_feature(shop, app):
    client, business_id, _product, _customer = shop
    assert client.get('/credit/').status_code == 200        # trial includes it

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    db.session.commit()

    response = client.get('/credit/', follow_redirects=True)
    assert 'not included in your current plan' in response.get_data(as_text=True)


def test_without_the_feature_every_sale_settles_in_full(shop):
    """Letting a business build a debt it cannot see or chase would quietly lose
    them money, so below the tier a sale is always treated as paid."""
    client, business_id, product, customer = shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code='basic').one().id
    subscription.status = 'active'
    db.session.commit()

    sale = sell(client, product, customer, quantity=8, settlement='credit')

    assert sale_balance(sale) == Decimal('0')
    assert credit.total_outstanding(business_id) == Decimal('0')


def test_sales_staff_can_take_payments_but_not_all_staff_can(shop, make_staff, business_fixture=None):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)

    sales_staff = make_staff(business_id, 'Sales Staff', 'sales@x.example.com')
    assert sales_staff.get('/credit/').status_code == 200

    inventory = make_staff(business_id, 'Inventory Staff', 'inv@x.example.com')
    assert inventory.get('/credit/').status_code == 403
    assert inventory.get(f'/credit/sale/{sale.id}/pay').status_code == 403


def test_a_settled_sale_says_so_on_its_own_statement_row(shop):
    """The Paid column on a sale row is always blank - the money arrives as its
    own row, sorted by its own date, which can be pages away. Without a
    settlement marker on the sale itself, a customer who has paid in full still
    reads as owing, and users conclude the payment was never recorded."""
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)        # 800 on credit

    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '800.00', 'method': 'momo', 'reference': 'MP260804.7788',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    events = credit.statement(business_id, customer.id)
    sale_row = next(e for e in events if e['kind'] == 'sale')
    payment_row = next(e for e in events if e['kind'] == 'payment')

    assert sale_row['status'] == 'paid'
    assert sale_row['settled'] == Decimal('800.00')
    assert sale_row['outstanding'] == Decimal('0')
    # The payment has to name what it cleared, or the two rows stay unconnected.
    assert payment_row['sale_id'] == sale.id
    # The ledger arithmetic is unchanged: charged less paid still nets to zero.
    assert events[-1]['balance'] == Decimal('0')


def test_a_part_paid_sale_shows_what_is_still_owed(shop):
    client, business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)        # 800 on credit

    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '300.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    sale_row = next(e for e in credit.statement(business_id, customer.id)
                    if e['kind'] == 'sale')
    assert sale_row['status'] == 'partial'
    assert sale_row['settled'] == Decimal('300.00')
    assert sale_row['outstanding'] == Decimal('500.00')


def test_settlement_reflects_the_as_of_date_not_todays_payments(shop):
    """An historical statement must not credit a sale with money that had not
    arrived by the date it was run - otherwise a statement printed for a
    customer contradicts the balance printed beside it."""
    client, business_id, product, customer = shop
    five_days_ago = TODAY - datetime.timedelta(days=5)
    sale = sell(client, product, customer, quantity=8, when=five_days_ago)

    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '800.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    as_of = TODAY - datetime.timedelta(days=3)
    earlier = next(e for e in credit.statement(business_id, customer.id, as_of=as_of)
                   if e['kind'] == 'sale')
    assert earlier['status'] == 'credit'
    assert earlier['outstanding'] == Decimal('800.00')

    now = next(e for e in credit.statement(business_id, customer.id)
               if e['kind'] == 'sale')
    assert now['status'] == 'paid'


def test_the_statement_page_shows_the_settlement_marker(shop):
    """A route-level test because the service returning the right dict is only
    half of it - the template has to render it."""
    client, _business_id, product, customer = shop
    sale = sell(client, product, customer, quantity=8)
    client.post(f'/credit/sale/{sale.id}/pay', data={
        'amount': '800.00', 'method': 'cash', 'reference': '',
        'paid_on': TODAY.isoformat(), 'notes': '',
    }, follow_redirects=True)

    body = client.get(f'/credit/customer/{customer.id}').get_data(as_text=True)
    assert 'Settled' in body
    assert f'against Sale #{sale.id}' in body
