"""The guided tour — F-50.

A pop-up that walks someone through the app, which is a thing you can get badly
wrong in three ways: showing it forever, showing it to people who cannot use
half of what it points at, and trapping them inside it.

The steps anchor to real elements rather than a list of coordinates, so the
permission gating comes for free — an element a clerk may not see is simply not
in their DOM, and `tour.js` drops any step whose anchor is missing. These tests
pin that property, because the alternative is a second list of who-sees-what
drifting away from the first.
"""
import datetime
import re

import pytest

from auth.models import AuditLog, User
from extensions import db


def tour_block(body):
    """The inline script carrying the step definitions."""
    match = re.search(r'var steps = \[(.*?)\];', body, re.S)
    return match.group(1) if match else ''


def anchors(body):
    return re.findall(r"anchor:\s*'([^']+)'", tour_block(body))


@pytest.fixture
def owner(register):
    client, business_id = register()
    return client, business_id


# --- shown once ---------------------------------------------------------------

def test_a_new_owner_gets_the_tour(owner):
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)

    assert 'tour.js' in body
    assert 'var autoStart = true' in body
    assert anchors(body), 'no steps were defined'


def test_it_does_not_start_again_once_seen(owner):
    """The whole point of storing it. A tour that reappears every morning is an
    obstacle, not an introduction."""
    client, _business_id = owner
    client.post('/auth/tour/done', data={'reason': 'completed'})

    body = client.get('/').get_data(as_text=True)

    assert 'var autoStart = false' in body
    # ...but the machinery is still there, so it can be replayed on request.
    assert 'tour.js' in body
    assert 'tour-replay' in body


def test_closing_it_early_counts_as_seen(owner):
    """Someone who shut it on step two has answered. Asking again tomorrow
    ignores the answer."""
    client, _business_id = owner
    client.post('/auth/tour/done', data={'reason': 'closed'})

    user = User.query.filter_by(email='owner@ab.example.com').one()
    assert user.tour_seen_at is not None
    assert 'var autoStart = false' in client.get('/').get_data(as_text=True)


def test_marking_it_seen_twice_keeps_the_first_time(owner):
    """Idempotent: the fetch is fired from a page that may be reloaded, and a
    later timestamp would quietly rewrite when this person was introduced."""
    client, _business_id = owner
    client.post('/auth/tour/done', data={'reason': 'completed'})
    first = User.query.filter_by(email='owner@ab.example.com').one().tour_seen_at

    client.post('/auth/tour/done', data={'reason': 'closed'})
    again = User.query.filter_by(email='owner@ab.example.com').one().tour_seen_at

    assert again == first
    assert AuditLog.query.filter_by(action='user.tour_seen').count() == 1


def test_it_answers_the_fetch_with_no_body(owner):
    client, _business_id = owner
    response = client.post('/auth/tour/done', data={'reason': 'completed'})

    assert response.status_code == 204
    assert response.get_data() == b''


def test_a_signed_out_visitor_cannot_mark_it_seen(client):
    response = client.post('/auth/tour/done', data={'reason': 'completed'})
    assert response.status_code in (302, 401)


# --- it only points at what this person can reach -----------------------------

def test_a_clerk_is_not_walked_through_what_they_cannot_open(owner, make_staff):
    """The property the whole design rests on. Steps anchor to sidebar ids that
    are already permission-gated, so a step for Administration cannot survive
    for someone who has no Administration group. If this ever fails, the tour
    has grown its own idea of who sees what."""
    _client, business_id = owner
    clerk = make_staff(business_id, 'Sales Staff', 'clerk@ab.example.com',
                       permissions=['products.view', 'sales.view'])

    body = clerk.get('/').get_data(as_text=True)

    # The step list is the same for everyone; the filtering happens in the
    # browser against the DOM. So what must be true is that the elements are
    # absent - which is what tour.js keys off.
    assert 'id="nav-group-admin"' not in body
    assert 'id="nav-group-purchasing"' not in body
    assert 'id="nav-products"' in body


def test_the_tour_drops_steps_whose_anchor_is_missing(owner):
    """Asserted against the script itself: this is the line that does it."""
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)

    worker = client.get('/static/js/tour.js').get_data(as_text=True)
    assert 'applicable' in worker
    assert "document.querySelector(step.anchor) !== null" in worker


def test_every_step_points_at_something_that_exists_for_an_owner(owner, make_product):
    """A step aimed at an id nobody renders is silently dropped, so a typo in an
    anchor would make the tour quietly shorter and nothing would ever say so."""
    client, business_id = owner
    make_product(business_id, sku='BA-750')          # so the checklist is present

    body = client.get('/').get_data(as_text=True)

    for anchor in anchors(body):
        assert anchor.startswith('#'), anchor
        assert f'id="{anchor[1:]}"' in body, f'{anchor} is not on the dashboard'


# --- the drawer, and getting out ----------------------------------------------

def test_a_nav_step_opens_the_drawer_on_a_phone(owner):
    """Below 992px the sidebar is off-canvas, so a step pointing at a nav item
    is pointing at something not on screen."""
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert 'setDrawer' in worker
    assert 'DESKTOP_MIN' in worker
    assert "sidebar.classList.toggle('show', wanted)" in worker


def test_a_nav_step_opens_a_collapsed_group_first(owner):
    """F-49 folded the sidebar, so half the anchors now start inside a shut
    panel with no height to point at."""
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert 'revealGroup' in worker
    assert "closest('.nav-group-items')" in worker


def test_there_is_always_a_way_out(owner):
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert "'Escape'" in worker
    assert "self.finish('closed')" in worker
    assert 'Close the tour' in worker


def test_skip_and_close_are_different_things(owner):
    """Skip moves past a step; close ends the tour. Collapsing them loses the
    distinction the user asked for."""
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert re.search(r"skip\.addEventListener\('click',\s*function\s*\(\)\s*\{\s*self\.go\(1\)", worker)
    assert re.search(r"close\.addEventListener\('click',\s*function\s*\(\)\s*\{\s*self\.finish\('closed'\)", worker)


def test_a_failed_record_does_not_break_the_page(owner):
    """The fetch fires from a page the user is still reading, and on a market-day
    connection it is the most likely thing here to fail."""
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert '.catch(' in worker


# --- the assets are ours ------------------------------------------------------

def test_the_tour_loads_nothing_from_another_origin(owner):
    """Same rule as 2.4a: a service worker cannot reliably cache a cross-origin
    response, and this has to work on the connection the product is built for."""
    client, _business_id = owner
    body = client.get('/').get_data(as_text=True)

    assert client.get('/static/js/tour.js').status_code == 200
    assert client.get('/static/css/tour.css').status_code == 200
    assert 'cdn.' not in body
    assert '//unpkg' not in body


# --- the record is written once, whoever asks -------------------------------

def test_a_second_request_cannot_double_write_even_from_a_stale_read(owner, app):
    """A conditional UPDATE, not read-then-write.

    Two requests - a double click, a retry, the same person finishing on two
    devices - would both see None and both write. Simulated here by marking the
    row through a *separate* session, so the request's own identity map still
    holds the old value: an in-memory check would sail past it, and the database
    is the only thing that can settle who was first.
    """
    from sqlalchemy.orm import Session

    client, _business_id = owner
    user = User.query.filter_by(email='owner@ab.example.com').one()

    other = Session(bind=db.engine)
    try:
        other.execute(
            db.text('UPDATE "user" SET tour_seen_at = :when WHERE id = :id'),
            {'when': datetime.datetime(2020, 1, 1), 'id': user.id})
        other.commit()
    finally:
        other.close()

    response = client.post('/auth/tour/done', data={'reason': 'completed'})

    assert response.status_code == 204
    db.session.expire_all()
    assert User.query.get(user.id).tour_seen_at == datetime.datetime(2020, 1, 1)
    assert AuditLog.query.filter_by(action='user.tour_seen').count() == 0


def test_the_endpoint_records_it_when_nobody_has(owner):
    """The other half: the conditional must still fire the first time."""
    client, _business_id = owner
    client.post('/auth/tour/done', data={'reason': 'completed'})

    user = User.query.filter_by(email='owner@ab.example.com').one()
    assert user.tour_seen_at is not None
    assert AuditLog.query.filter_by(action='user.tour_seen').count() == 1


# --- it behaves like the modal it announces itself as -------------------------

def test_tab_is_kept_inside_the_tour(owner):
    """The root carries aria-modal, which tells a screen reader the rest of the
    page is inert. Without a trap that is simply untrue - Tab walks out into
    content that is dimmed, unreachable by mouse, and still focusable."""
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert 'trapTab' in worker
    assert "event.key === 'Tab'" in worker
    assert 'reachable' in worker


def test_focus_is_given_back_when_the_tour_closes(owner):
    """Otherwise a keyboard user is dropped at the top of the document having
    lost their place entirely."""
    client, _business_id = owner
    worker = client.get('/static/js/tour.js').get_data(as_text=True)

    assert 'previousFocus = document.activeElement' in worker
    assert 'this.previousFocus.focus(' in worker


def test_the_dimmed_page_does_not_take_clicks(owner):
    """It looks disabled. It was not: pointer-events was none, so a click landed
    on whatever was underneath."""
    client, _business_id = owner
    css = client.get('/static/css/tour.css').get_data(as_text=True)

    root = css[css.index('.tour-root {'):css.index('.tour-spotlight')]
    assert 'pointer-events: auto' in root
