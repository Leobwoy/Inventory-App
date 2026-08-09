"""The subscription lifecycle.

One rule sits behind every test here: **the job is not the authority.** Access
is decided by `limits.effective_plan` reading the dates on each request, so
these transitions only make the stored status agree with what was already true.
That is why several of these tests check that entitlement is unchanged by
whether the reconcile ran - it is the property that makes a missed scheduled run
survivable, and a free instance that sleeps will miss runs.
"""
import datetime
import os

import pytest

from billing.models import Plan, Subscription
from billing.plans import GRACE_DAYS
from extensions import db
from services import limits, subscriptions

NOW = datetime.datetime.utcnow()


def sub_for(business_id):
    return Subscription.query.filter_by(business_id=business_id).one()


def put_on(business_id, status, plan='standard', trial_ends_at=..., paid_through=...):
    """Place a subscription in a given state. Returns it."""
    subscription = sub_for(business_id)
    subscription.status = status
    subscription.plan_id = Plan.query.filter_by(code=plan).one().id
    if trial_ends_at is not ...:
        subscription.trial_ends_at = trial_ends_at
    if paid_through is not ...:
        subscription.paid_through = paid_through
    db.session.commit()
    return subscription


@pytest.fixture
def shop(register):
    client, business_id = register()
    return client, business_id


# --- the transitions ---------------------------------------------------------

def test_a_finished_trial_becomes_free(shop):
    client, business_id = shop
    put_on(business_id, 'trialing',
           trial_ends_at=NOW - datetime.timedelta(days=1))

    assert subscriptions.reconcile(sub_for(business_id)) == 'free'
    assert sub_for(business_id).status == 'free'


def test_a_running_trial_is_left_alone(shop):
    client, business_id = shop
    put_on(business_id, 'trialing',
           trial_ends_at=NOW + datetime.timedelta(days=3))

    assert subscriptions.reconcile(sub_for(business_id)) is None
    assert sub_for(business_id).status == 'trialing'


def test_a_lapsed_paid_plan_gets_the_grace_period_first(shop):
    """Not straight to free. Mobile money cannot renew on its own, so a lapse
    means "they have not paid yet today", not "they left"."""
    client, business_id = shop
    put_on(business_id, 'active', paid_through=NOW - datetime.timedelta(hours=1))

    assert subscriptions.reconcile(sub_for(business_id)) == 'grace'
    assert sub_for(business_id).status == 'grace'


def test_grace_runs_out_eventually(shop):
    client, business_id = shop
    put_on(business_id, 'grace',
           paid_through=NOW - datetime.timedelta(days=GRACE_DAYS + 1))

    assert subscriptions.reconcile(sub_for(business_id)) == 'free'
    assert sub_for(business_id).status == 'free'


def test_a_long_lapsed_plan_does_not_stop_off_in_grace(shop):
    """One step, not two. `effective_plan` treats active and grace alike - both
    keep the plan until paid_through + grace - so a row that lapsed months ago
    has no grace left to enter. Parking it there for a day would be this module
    contradicting the read path it exists to follow, and on a daily schedule
    that contradiction is exactly what anyone looking would see."""
    client, business_id = shop
    put_on(business_id, 'active',
           paid_through=NOW - datetime.timedelta(days=GRACE_DAYS + 30))

    assert subscriptions.reconcile(sub_for(business_id)) == 'free'
    assert sub_for(business_id).status == 'free'


def test_a_plan_that_lapsed_yesterday_still_gets_its_grace(shop):
    """The distinction the step above must not flatten."""
    client, business_id = shop
    put_on(business_id, 'active', paid_through=NOW - datetime.timedelta(days=1))

    assert subscriptions.reconcile(sub_for(business_id)) == 'grace'
    assert sub_for(business_id).status == 'grace'


def test_grace_that_has_not_run_out_is_left_alone(shop):
    client, business_id = shop
    put_on(business_id, 'grace',
           paid_through=NOW - datetime.timedelta(days=GRACE_DAYS - 1))

    assert subscriptions.reconcile(sub_for(business_id)) is None


def test_a_free_subscription_has_nowhere_left_to_fall(shop):
    """Reconciling repeatedly must be a no-op, because it will happen daily
    forever for every business that has ever lapsed."""
    client, business_id = shop
    put_on(business_id, 'free', plan='free')

    assert subscriptions.reconcile(sub_for(business_id)) is None
    assert subscriptions.reconcile(sub_for(business_id)) is None


# --- the trap: a free status still names a plan ------------------------------

def test_downgrading_takes_the_paid_plan_away_too(shop):
    """`effective_plan` reads status == 'free' as "on the plan named here, with
    no expiry" - that is how a comped account works. So flipping the status
    without rewriting plan_id would grant the paid plan permanently: the exact
    opposite of a downgrade, and it would never expire again."""
    client, business_id = shop
    put_on(business_id, 'trialing', plan='standard',
           trial_ends_at=NOW - datetime.timedelta(days=1))

    subscriptions.reconcile(sub_for(business_id))
    db.session.commit()

    assert sub_for(business_id).plan.code == 'free'
    assert limits.effective_plan(business_id).code == 'free'


def test_a_downgrade_stops_the_features_that_were_paid_for(shop):
    """Right through the sequence: paid, then lapsed, then downgraded."""
    client, business_id = shop
    put_on(business_id, 'active', plan='standard',
           paid_through=NOW + datetime.timedelta(days=30))
    assert limits.has_feature('offline', business_id)

    # Time passes. The read path withdraws it here, before anything is written -
    # which is the point.
    put_on(business_id, 'active', plan='standard',
           paid_through=NOW - datetime.timedelta(days=GRACE_DAYS + 1))
    assert not limits.has_feature('offline', business_id)

    subscriptions.reconcile(sub_for(business_id))     # -> grace
    subscriptions.reconcile(sub_for(business_id))     # -> free
    db.session.commit()

    # And still off once the status says free, which is the trap: a free status
    # with a paid plan_id left behind would hand it back permanently.
    assert not limits.has_feature('offline', business_id)


def test_a_downgrade_stops_a_renewal_being_assumed(shop):
    client, business_id = shop
    subscription = put_on(business_id, 'grace', plan='standard',
                          paid_through=NOW - datetime.timedelta(days=GRACE_DAYS + 1))
    subscription.auto_renew = True
    db.session.commit()

    subscriptions.reconcile(sub_for(business_id))
    assert sub_for(business_id).auto_renew is False
    assert sub_for(business_id).paid_through is None


# --- it agrees with the read path, which is what decides access --------------

@pytest.mark.parametrize('status,trial_ends_at,paid_through', [
    ('trialing', NOW - datetime.timedelta(days=1), None),
    ('trialing', NOW + datetime.timedelta(days=1), None),
    ('active', None, NOW - datetime.timedelta(days=1)),
    ('active', None, NOW + datetime.timedelta(days=1)),
    ('grace', None, NOW - datetime.timedelta(days=GRACE_DAYS + 1)),
    ('grace', None, NOW - datetime.timedelta(days=1)),
])
def test_reconciling_never_changes_what_a_business_may_do(
        shop, status, trial_ends_at, paid_through):
    """The property the whole design rests on. If running the job could change
    entitlement, then a skipped run would silently change it too - and on a free
    instance that sleeps, skipped runs are certain."""
    client, business_id = shop
    put_on(business_id, status, plan='standard',
           trial_ends_at=trial_ends_at, paid_through=paid_through)

    before = limits.effective_plan(business_id).code

    subscriptions.reconcile(sub_for(business_id))
    db.session.commit()

    assert limits.effective_plan(business_id).code == before


def test_a_missing_free_plan_refuses_rather_than_guesses(shop):
    """Better a loud failure than a paid plan left on a free status."""
    client, business_id = shop
    put_on(business_id, 'trialing', plan='standard',
           trial_ends_at=NOW - datetime.timedelta(days=1))
    Plan.query.filter_by(code='free').delete()
    db.session.flush()

    with pytest.raises(RuntimeError, match='free plan'):
        subscriptions.reconcile(sub_for(business_id))
    db.session.rollback()


# --- what is due, and the batch ----------------------------------------------

def test_pending_finds_only_what_is_actually_due(shop, register):
    client, business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='o@kd.example.com')

    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))
    put_on(other_id, 'trialing', trial_ends_at=NOW + datetime.timedelta(days=5))

    due = [s.business_id for s in subscriptions.pending()]
    assert business_id in due
    assert other_id not in due


def test_the_batch_finishes_off_a_spent_grace_period(shop, register):
    """The scheduled run only ever touches rows `pending()` hands it, so a wrong
    grace clause there leaves every lapsed business sitting in `grace` for good.
    Access would still be denied correctly - but nothing would ever settle, and
    the console and every reminder would go on describing a grace period that
    ended months ago."""
    client, business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='o@kd.example.com')
    put_on(business_id, 'grace',
           paid_through=NOW - datetime.timedelta(days=GRACE_DAYS + 1))
    put_on(other_id, 'grace',
           paid_through=NOW - datetime.timedelta(days=GRACE_DAYS - 1))

    due = [s.business_id for s in subscriptions.pending()]
    assert business_id in due
    assert other_id not in due

    summary = subscriptions.reconcile_all()
    assert summary['moved'] == {business_id: 'free'}
    assert sub_for(other_id).status == 'grace'


def test_the_batch_moves_everything_that_is_due(shop, register):
    client, business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='o@kd.example.com')
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))
    put_on(other_id, 'active', paid_through=NOW - datetime.timedelta(hours=2))

    summary = subscriptions.reconcile_all()

    assert summary['moved'][business_id] == 'free'
    assert summary['moved'][other_id] == 'grace'
    assert summary['failed'] == []


def test_one_business_failing_does_not_hold_up_the_rest(shop, register, monkeypatch):
    """The scheduled run touches every tenant on the platform. One unwritable
    row must not leave the others stuck in a status that expired weeks ago."""
    client, business_id = shop
    _other, other_id = register(name='Kumasi Drinks', email='o@kd.example.com')
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))
    put_on(other_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))

    real = subscriptions.reconcile

    def explode_for_one(subscription, now=None):
        if subscription.business_id == business_id:
            raise RuntimeError('this row will not write')
        return real(subscription, now)

    monkeypatch.setattr(subscriptions, 'reconcile', explode_for_one)
    summary = subscriptions.reconcile_all()

    assert summary['failed'] == [business_id]
    assert summary['moved'] == {other_id: 'free'}
    assert sub_for(other_id).status == 'free'


def test_every_transition_is_on_the_record(shop):
    """A business that finds a feature gone is owed an answer to "since when,
    and why". Nobody triggered this one, so nothing else records it."""
    from auth.models import AuditLog

    client, business_id = shop
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))
    subscriptions.reconcile(sub_for(business_id))
    db.session.commit()

    entry = (AuditLog.query
             .filter_by(business_id=business_id,
                        action='billing.subscription_transitioned').one())
    assert entry.user_id is None            # time did this, not a person
    assert 'trial' in (entry.details_json or '').lower()


# --- lazily, when the business uses the app ----------------------------------

def test_using_the_app_brings_the_subscription_up_to_date(shop):
    client, business_id = shop
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))

    # Signing up already ran today's check. In life the marker holds an older
    # date by the time a trial lapses; here the whole test is one minute long.
    with client.session_transaction() as session:
        session.pop('subscription_checked', None)

    client.get('/')

    assert sub_for(business_id).status == 'free'


def test_the_lazy_check_does_not_run_on_every_request(shop):
    """It would cost a query on all fifty-odd routes to write something on
    approximately none of them."""
    client, business_id = shop
    client.get('/')                                   # first visit does the check

    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))
    client.get('/')                                   # same day, so skipped

    assert sub_for(business_id).status == 'trialing'


def test_a_failed_lazy_check_still_serves_the_page(shop, monkeypatch):
    """Nobody asked for a reconcile - they asked for the dashboard. Access was
    never waiting on this, so a failure here must not be visible."""
    client, business_id = shop

    def explode(*args, **kwargs):
        raise RuntimeError('the database blinked')

    monkeypatch.setattr(subscriptions, 'reconcile_business', explode)
    with client.session_transaction() as session:
        session.pop('subscription_checked', None)   # or the check is skipped

    assert client.get('/').status_code == 200


def test_a_failed_lazy_check_is_tried_again_rather_than_written_off(shop, monkeypatch):
    """The marker is written after the work, not before it. Written before, a
    connection that blinked once would skip this business until tomorrow - and
    the business the lazy trigger is for is the one using the app right now."""
    client, business_id = shop
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))

    attempts = []
    real = subscriptions.reconcile_business

    def fail_once(bid, now=None):
        attempts.append(bid)
        if len(attempts) == 1:
            raise RuntimeError('the database blinked')
        return real(bid, now)

    monkeypatch.setattr(subscriptions, 'reconcile_business', fail_once)
    with client.session_transaction() as session:
        session.pop('subscription_checked', None)

    client.get('/')                        # fails, and must not mark the day done
    with client.session_transaction() as session:
        assert 'subscription_checked' not in session

    client.get('/')                        # so the next page tries it again
    assert len(attempts) == 2
    assert sub_for(business_id).status == 'free'


def test_the_lazy_check_ignores_signed_out_visitors(app, monkeypatch):
    """The login page is fetched by people with no business to reconcile.

    Checked through the session marker rather than by watching for a call: the
    call would fail on current_user.business_id and be swallowed anyway, so a
    test that only watched for it would pass with the guard deleted. Writing the
    marker is the part that survives - and it puts a session cookie on every
    anonymous visitor to every page.
    """
    called = []
    monkeypatch.setattr(subscriptions, 'reconcile_business',
                        lambda business_id, now=None: called.append(business_id))

    client = app.test_client()
    assert client.get('/auth/login').status_code == 200

    assert called == []
    with client.session_transaction() as session:
        assert 'subscription_checked' not in session


# --- on a schedule -----------------------------------------------------------

def test_the_cron_endpoint_applies_what_is_due(client, register, monkeypatch):
    monkeypatch.setenv('CRON_SECRET', 'a-secret-worth-keeping')
    _c, business_id = register()
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))

    response = client.post('/api/v1/cron/subscriptions',
                           headers={'X-Cron-Key': 'a-secret-worth-keeping'})

    assert response.status_code == 200
    assert response.get_json()['moved'] == {str(business_id): 'free'}
    assert sub_for(business_id).status == 'free'


def test_the_cron_endpoint_refuses_a_wrong_secret(client, register, monkeypatch):
    monkeypatch.setenv('CRON_SECRET', 'a-secret-worth-keeping')
    _c, business_id = register()
    put_on(business_id, 'trialing', trial_ends_at=NOW - datetime.timedelta(days=1))

    response = client.post('/api/v1/cron/subscriptions',
                           headers={'X-Cron-Key': 'not-the-secret'})

    assert response.status_code == 404
    assert sub_for(business_id).status == 'trialing'


def test_the_cron_endpoint_refuses_no_secret_at_all(client, monkeypatch):
    monkeypatch.setenv('CRON_SECRET', 'a-secret-worth-keeping')
    assert client.post('/api/v1/cron/subscriptions').status_code == 404


def test_a_secret_with_an_accent_in_it_is_refused_not_crashed(client, monkeypatch):
    """hmac.compare_digest refuses two str arguments when either holds a
    non-ASCII character. Compared as text, a passphrase secret would therefore
    raise on every call - turning the guard into a 500, which tells anyone
    probing that the endpoint is real and that something behind it is broken."""
    monkeypatch.setenv('CRON_SECRET', 'sécret-phrase-non-ascii')

    assert client.post('/api/v1/cron/subscriptions',
                       headers={'X-Cron-Key': 'wrong'}).status_code == 404
    assert client.post('/api/v1/cron/subscriptions',
                       headers={'X-Cron-Key': 'sécret-phrase-non-ascii'}
                       ).status_code == 200


def test_an_unconfigured_cron_endpoint_does_not_exist(client, monkeypatch):
    """404 rather than 500 or 403. An endpoint nobody has set up should not
    admit that it might work with the right header."""
    monkeypatch.delenv('CRON_SECRET', raising=False)

    assert client.post('/api/v1/cron/subscriptions',
                       headers={'X-Cron-Key': ''}).status_code == 404
    assert client.post('/api/v1/cron/subscriptions',
                       headers={'X-Cron-Key': 'anything'}).status_code == 404


def test_the_cron_endpoint_is_exempt_from_csrf(app, monkeypatch):
    """A scheduler has no session and cannot fetch a token first, so without the
    exemption every scheduled run would be refused in production - where CSRF is
    on, and where the suite's default of off would have hidden it.

    Protection is switched back on for this one test and the post carries no
    token. The login post first is not decoration: it proves the switch actually
    took, so a green result here cannot mean "CSRF was off anyway".
    """
    monkeypatch.setenv('CRON_SECRET', 'a-secret-worth-keeping')
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    client = app.test_client()

    guarded = client.post('/auth/login', data={'email': 'x@y.example.com',
                                               'password': 'whatever'})
    assert guarded.status_code == 400, 'CSRF protection did not switch on'

    response = client.post('/api/v1/cron/subscriptions',
                           headers={'X-Cron-Key': 'a-secret-worth-keeping'})
    assert response.status_code == 200


def test_the_cron_endpoint_is_not_a_way_in(client, register, monkeypatch):
    """It runs without a login, so it must not be able to read anything."""
    monkeypatch.setenv('CRON_SECRET', 'a-secret-worth-keeping')
    _c, business_id = register(name='Accra Wholesale')

    body = client.post('/api/v1/cron/subscriptions',
                       headers={'X-Cron-Key': 'a-secret-worth-keeping'}).get_data(as_text=True)

    assert 'Accra' not in body


# --- the console stops contradicting itself ----------------------------------

def test_the_console_shows_the_status_that_is_actually_in_effect(console, register):
    """It read Trial beside a Kiosk plan on the same row: the plan column comes
    from effective_plan, which had already worked the expiry out."""
    _c, business_id = register(name='Accra Wholesale')
    put_on(business_id, 'trialing', plan='standard',
           trial_ends_at=NOW - datetime.timedelta(days=30))

    body = console.get('/platform/businesses').get_data(as_text=True)
    row = body[body.index('Accra Wholesale'):][:600]

    assert 'Trial' not in row
    assert 'Free' in row or 'free' in row
