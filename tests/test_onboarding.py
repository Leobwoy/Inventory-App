"""F-45 — telling a new business what to do, and what it is on.

Two things a new business was never told: that a trial exists at all, and what
to do first. Registration mentioned neither, and the dashboard went straight to
stat cards reading zero.

The checklist is **derived**, like the alerts and for the same reason. A stored
checklist can be ticked while the thing is not true, and a dismissed one goes on
saying "all set" to a business with nothing in it. Here a step is done because
the data says so, and undoing the work un-ticks it.
"""
import datetime

import pytest

from billing.models import Plan, Subscription
from billing.plans import TRIAL_DAYS
from extensions import db
from services import onboarding


@pytest.fixture
def shop(register):
    client, business_id = register()
    return client, business_id


def set_subscription(business_id, status, plan='trial', trial_ends_at=..., paid_through=...):
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.status = status
    subscription.plan_id = Plan.query.filter_by(code=plan).one().id
    if trial_ends_at is not ...:
        subscription.trial_ends_at = trial_ends_at
    if paid_through is not ...:
        subscription.paid_through = paid_through
    db.session.commit()
    return subscription


# --- the checklist reflects real data ----------------------------------------

def test_a_brand_new_business_has_nothing_ticked(shop):
    _client, business_id = shop

    state = onboarding.state_for(business_id)

    assert state['done'] == 0
    assert state['fresh'] is True
    assert state['complete'] is False
    assert state['next']['key'] == 'product'


def test_adding_a_product_ticks_the_first_step(shop, make_product):
    _client, business_id = shop
    make_product(business_id, sku='BA-750')

    state = onboarding.state_for(business_id)

    assert state['done'] == 1
    assert state['next']['key'] == 'supplier'


def test_deactivating_the_only_product_unticks_it(shop, make_product):
    """Derived, not stored. The point of computing it is that it cannot go on
    claiming a step is done after the thing stops being true."""
    from products.models import Product

    _client, business_id = shop
    product = make_product(business_id, sku='BA-750')
    assert onboarding.state_for(business_id)['done'] == 1

    db.session.get(Product, product.id).is_active = False
    db.session.commit()

    assert onboarding.state_for(business_id)['done'] == 0


def test_the_steps_are_in_the_order_the_app_forces(shop):
    """You cannot receive stock without an order, or sell what you never
    received. A checklist in any other order sends someone into a dead end."""
    _client, business_id = shop

    assert [s['key'] for s in onboarding.steps(business_id)] == [
        'product', 'supplier', 'order', 'stock', 'sale']


def test_every_step_points_at_a_page_that_exists(shop, app):
    """A checklist whose links 404 is worse than no checklist."""
    _client, business_id = shop
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}

    for step in onboarding.steps(business_id):
        assert step['endpoint'] in endpoints, step['key']


def test_the_checklist_stays_inside_the_business(shop, register, make_product):
    _client, business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='o@kd.example.com')
    make_product(other_id, sku='KD-1')

    assert onboarding.state_for(business_id)['done'] == 0
    assert onboarding.state_for(other_id)['done'] == 1


# --- the dashboard ------------------------------------------------------------

def test_the_dashboard_welcomes_a_business_with_nothing_in_it(shop):
    client, _business_id = shop

    body = client.get('/').get_data(as_text=True)

    assert 'Welcome to TrackTrack' in body
    assert 'Add your first product' in body


def test_the_checklist_disappears_once_everything_is_done(shop, monkeypatch):
    """No dismiss button anywhere, because there is nothing stored to dismiss —
    it goes when the work is done and comes back if the work is undone."""
    client, business_id = shop
    monkeypatch.setattr(onboarding, 'state_for',
                        lambda bid: {'steps': [], 'done': 5, 'total': 5,
                                     'complete': True, 'next': None, 'fresh': False})

    body = client.get('/').get_data(as_text=True)

    assert 'Welcome to TrackTrack' not in body
    assert 'Finish setting up' not in body


def test_a_partly_set_up_business_is_told_only_the_next_thing(shop, make_product):
    client, business_id = shop
    make_product(business_id, sku='BA-750')

    body = client.get('/').get_data(as_text=True)

    assert 'Finish setting up' in body
    assert 'Welcome to TrackTrack' not in body


# --- the trial is mentioned before signing up --------------------------------

def test_the_registration_page_says_what_the_trial_is(client):
    """It said nothing at all, so the offer was invisible at the one moment
    someone is deciding whether to bother."""
    body = client.get('/auth/register').get_data(as_text=True)

    assert f'{TRIAL_DAYS} days' in body


def test_the_registration_page_does_not_advertise_the_free_tier(client):
    """Deliberate. It is listed on the billing page for anyone who looks, but
    answering "what if I do nothing?" here answers it at the wrong moment."""
    body = client.get('/auth/register').get_data(as_text=True)

    assert 'Kiosk' not in body
    assert 'free plan' not in body.lower()
    assert 'free tier' not in body.lower()


# --- the countdown, and what happens when it runs out ------------------------

def test_a_running_trial_shows_the_days_left(shop):
    client, business_id = shop
    set_subscription(business_id, 'trialing',
                     trial_ends_at=datetime.datetime.utcnow() + datetime.timedelta(days=9))

    state = onboarding.trial_state(business_id)
    assert state['phase'] == 'trialing'
    assert state['days'] == 9
    assert '9 days left' in client.get('/').get_data(as_text=True)


def test_a_finished_trial_says_plainly_what_happened(shop):
    """Someone who works out they have been downgraded by finding a feature
    missing does not come back."""
    client, business_id = shop
    set_subscription(business_id, 'free', plan='free',
                     trial_ends_at=datetime.datetime.utcnow() - datetime.timedelta(days=1))

    body = client.get('/').get_data(as_text=True)

    assert 'Your trial has ended' in body
    assert 'Kiosk' in body                        # names what they are on now
    assert 'still here' in body                   # and that nothing was deleted


def test_the_ended_notice_stops_after_a_fortnight(shop):
    """The moment that matters is the first login after the downgrade. A month
    later it is nagging."""
    client, business_id = shop
    set_subscription(
        business_id, 'free', plan='free',
        trial_ends_at=datetime.datetime.utcnow()
        - datetime.timedelta(days=onboarding.ENDED_NOTICE_DAYS + 1))

    assert onboarding.trial_state(business_id) is None
    assert 'Your trial has ended' not in client.get('/').get_data(as_text=True)


def test_a_comped_business_is_never_told_its_trial_ran_out(shop):
    """A comped account is `status == 'free'` on a paid plan — identical to a
    lapsed trial in the status column alone. Reading only the status would tell
    a customer we chose to look after that they had run out."""
    client, business_id = shop
    set_subscription(business_id, 'free', plan='standard',
                     trial_ends_at=datetime.datetime.utcnow() - datetime.timedelta(days=1))

    assert onboarding.trial_state(business_id) is None
    assert 'trial has ended' not in client.get('/').get_data(as_text=True)


def test_a_paying_business_sees_no_trial_message_at_all(shop):
    client, business_id = shop
    set_subscription(business_id, 'active', plan='standard',
                     trial_ends_at=datetime.datetime.utcnow() - datetime.timedelta(days=40),
                     paid_through=datetime.datetime.utcnow() + datetime.timedelta(days=20))

    assert onboarding.trial_state(business_id) is None
    body = client.get('/').get_data(as_text=True)
    assert 'trial' not in body.lower()


def test_the_progress_track_is_not_bootstraps_near_white(client):
    """Bootstrap's `.progress` track is #e9ecef. On a dark card an empty bar
    renders as a solid light bar the full width of the card — reading as
    complete, the exact opposite of "0 of 5". Only visible in a browser, so it
    is asserted against the stylesheet that ships."""
    css = client.get('/static/css/style.css').get_data(as_text=True)

    assert '.progress {' in css
    assert 'background-color: rgba(148, 163, 184, 0.2)' in css


def test_the_whole_checklist_costs_one_query(shop, make_product):
    """Five separate EXISTS calls put the dashboard over its query budget the
    moment this shipped. The dashboard renders more than any other page, and an
    earlier version of it ran a query per product (F-14)."""
    from tests.test_queries import QueryCounter

    _client, business_id = shop
    make_product(business_id, sku='BA-750')

    with QueryCounter() as counter:
        onboarding.steps(business_id)

    assert len(counter.statements) == 1, counter.statements
