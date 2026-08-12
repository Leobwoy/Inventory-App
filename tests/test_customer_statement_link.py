"""Reaching a customer's statement from the Customers page.

It was only reachable through Money Owed — which means the full history of a
customer who has always paid on time, and therefore never appears in Money Owed
at all, could not be opened from anywhere.

The link is gated twice, because the page it opens is gated twice: `credit.view`
decides who may see what a customer owes, and the `credit_ledger` feature decides
whether this business bought the credit book. Showing it without either gives a
button that 403s, or an upsell disguised as a broken link.
"""
import pytest

from billing.models import Plan, Subscription
from extensions import db
from sales.models import Customer


@pytest.fixture
def shop(register):
    client, business_id = register()
    return client, business_id


def add_customer(client, name='Mensah Stores'):
    client.post('/sales/customers/add',
                data={'name': name, 'phone': '0244000111', 'address': 'Accra'},
                follow_redirects=True)
    return Customer.query.filter_by(name=name).one()


def test_an_owner_can_open_a_statement_from_the_customers_page(shop):
    client, _business_id = shop
    customer = add_customer(client)

    body = client.get('/sales/customers').get_data(as_text=True)

    assert f'/credit/customer/{customer.id}' in body


def test_the_link_lands_on_the_statement(shop):
    """A link is only worth adding if it goes somewhere that renders."""
    client, _business_id = shop
    customer = add_customer(client)

    response = client.get(f'/credit/customer/{customer.id}')

    assert response.status_code == 200
    assert 'Mensah Stores' in response.get_data(as_text=True)


def test_someone_without_credit_view_is_not_offered_it(shop, make_staff):
    """Managing customers and seeing what they owe are separate permissions, and
    the sales clerk who keeps the address book may not hold the second."""
    client, business_id = shop
    customer = add_customer(client)

    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['customers.view'])
    body = clerk.get('/sales/customers').get_data(as_text=True)

    assert f'/credit/customer/{customer.id}' not in body
    assert clerk.get(f'/credit/customer/{customer.id}').status_code == 403


def test_a_business_without_the_credit_feature_is_not_offered_it(shop):
    """On Kiosk the credit book is not included, so the button would be an
    upsell wearing the clothes of a broken link."""
    client, business_id = shop
    customer = add_customer(client)

    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.status = 'free'
    subscription.plan_id = Plan.query.filter_by(code='free').one().id
    db.session.commit()

    body = client.get('/sales/customers').get_data(as_text=True)

    assert f'/credit/customer/{customer.id}' not in body
