"""A downgrade takes access away immediately, and says so.

Invariant 10 has read the same way since it was written: *"Downgrading removes
access, not records: products deactivate, staff suspend, nothing is destroyed."*
Nothing did that. The caps were only ever consulted when **adding** something, so
a Distributor with four hundred products who dropped to Kiosk kept all four
hundred active and sellable, and every one of fifteen staff kept logging in. The
ceiling only stopped them creating number four hundred and one.

Two decisions shape what is here, both taken by the user:

**The Owner keeps their seat.** Kiosk has one. A literal "suspend everyone over
the cap" locks the last person out of a business that still owes money, and
`auth/routes.py` refuses to suspend an Owner anyway - so the business would be
unreachable and unable to pay.

**What is switched off stays visible.** The catalogue keeps every product,
marked, with what a bigger plan would give back. Hiding them would read as the
app having lost their stock.
"""
import datetime

import pytest

from auth.models import User
from billing.models import Plan, PaymentTransaction, Subscription
from extensions import db
from products.models import Product
from sales.models import Sale
from services import limits

NOW = datetime.datetime.utcnow()


def on_plan(business_id, code, paid_through=30):
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.plan_id = Plan.query.filter_by(code=code).one().id
    subscription.status = 'active'
    subscription.paid_through = NOW + datetime.timedelta(days=paid_through)
    db.session.commit()


@pytest.fixture
def big_shop(register, make_product, make_staff):
    """A Distributor with 25 products and four people, including the Owner."""
    client, business_id = register()
    for i in range(25):
        make_product(business_id, sku='P%02d' % i, name='Product %d' % i)
    for i in range(3):
        make_staff(business_id, 'Manager', 'm%d@x.example.com' % i)
    on_plan(business_id, 'advanced')
    return client, business_id


def stocked_fillers(make_product, business_id, count):
    """Products that are certainly safe: stock on the floor, so they lead."""
    return [make_product(business_id, sku='FILL-%02d' % i, name='Filler %d' % i,
                         stock=100) for i in range(count)]


def record_sales(business_id, product, units):
    import datetime

    from sales.models import Sale, SaleItem

    sale = Sale(business_id=business_id, sale_date=datetime.date.today())
    db.session.add(sale)
    db.session.flush()
    db.session.add(SaleItem(sale_id=sale.id, product_id=product.id, quantity=units,
                            price_at_sale=1, sell_unit='base'))
    db.session.commit()


def active_products(business_id):
    return Product.query.filter_by(business_id=business_id).filter(
        Product.is_active.isnot(False)).count()


def all_products(business_id):
    return Product.query.filter_by(business_id=business_id).count()


def active_users(business_id):
    return User.query.filter_by(business_id=business_id).filter(
        User.is_active.isnot(False)).count()


# --- the caps themselves -----------------------------------------------------

def test_the_caps_are_what_the_price_list_says(big_shop):
    """`billing/plans.py` is not read at runtime - it seeded this table once and
    every limit is read from the row. The two drifting apart is invisible until
    somebody trusts the file."""
    from billing.plans import PLANS

    declared = {row[0]: row[5] for row in PLANS}
    stored = {p.code: p.max_products for p in Plan.query.all()}

    assert stored == declared
    assert stored['free'] == 20
    assert stored['basic'] == 70
    assert stored['standard'] == 200
    assert stored['advanced'] == 500
    assert stored['custom'] is None


def test_the_trial_previews_the_plan_it_is_a_trial_of(big_shop):
    """Not in the list the user gave, and it has to move anyway: the trial grants
    the advanced tier, so leaving it unlimited would let somebody build 600
    products in a fortnight and lose a hundred the day it ended."""
    plans = {p.code: p for p in Plan.query.all()}

    assert plans['trial'].max_products == plans['advanced'].max_products
    assert plans['trial'].max_users == plans['advanced'].max_users


# --- what a downgrade actually does ------------------------------------------

def test_dropping_to_kiosk_switches_off_everything_over_the_cap(big_shop):
    _client, business_id = big_shop
    on_plan(business_id, 'free')

    limits.enforce_plan_limits(business_id)
    db.session.commit()

    assert active_products(business_id) == 20
    assert active_users(business_id) == 1


def test_nothing_is_ever_deleted(big_shop):
    """The records are the business's. The plan governs what can be done with
    them today, and that is all it governs."""
    _client, business_id = big_shop
    on_plan(business_id, 'free')

    limits.enforce_plan_limits(business_id)
    db.session.commit()

    assert all_products(business_id) == 25, 'a product row was destroyed'
    assert User.query.filter_by(business_id=business_id).count() == 4


def test_the_owner_is_never_the_one_suspended(big_shop):
    """Kiosk has one seat. Suspending everybody over the cap would take the
    Owner too, leaving nobody able to log in and pay - and auth/routes.py
    refuses to suspend an Owner in the first place, so the two would disagree.

    **Ownership is moved to the newest account first, and that is the whole
    test.** Written the obvious way it proved nothing: the Owner registers
    before any staff, so they hold the lowest id, and *any* ordering leaves them
    first. Falsification showed it staying green with the sort broken, the
    guard broken, and both broken together - it was passing on an accident of
    row order. A business that transfers ownership breaks that accident, and
    this is the only arrangement where keeping the Owner has to be deliberate.
    """
    from auth.models import Role

    _client, business_id = big_shop
    people = User.query.filter_by(business_id=business_id).order_by(User.id).all()
    owner_role = Role.query.filter_by(name=User.OWNER_ROLE).first()
    manager_role = Role.query.filter_by(name='Manager').first()
    people[0].role_id = manager_role.id
    people[-1].role_id = owner_role.id
    db.session.commit()
    assert people[-1].is_owner and not people[0].is_owner, 'the setup did not take'

    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    left = User.query.filter_by(business_id=business_id).filter(
        User.is_active.isnot(False)).all()
    assert len(left) == 1
    assert left[0].is_owner, 'the last account standing is not the Owner'
    assert left[0].id == people[-1].id


def test_stock_on_the_floor_outranks_a_proven_seller(register, make_product):
    """Which products stay sellable was chosen against real data, not in the
    abstract. The first rule written here was "keep the newest"; measured
    against the development catalogue it kept two products with no stock and no
    sales while retiring four of the best-selling lines, because a wholesaler's
    staples are the ones they have carried longest.

    Stock leads. Goods already paid for and sitting on the floor that the app
    will not let them sell is the sharpest version of this pain - a fast mover
    they are out of costs them nothing today.

    Nineteen stocked fillers plus one more stocked product fill Kiosk's twenty
    exactly, so the seller with an empty shelf is the one that has to go.
    """
    _client, business_id = register()
    stocked_fillers(make_product, business_id, 19)
    held = make_product(business_id, sku='HELD', name='On the floor', stock=400)
    empty_seller = make_product(business_id, sku='SOLD', name='Sells fast', stock=0)
    record_sales(business_id, empty_seller, 900)
    on_plan(business_id, 'free')

    limits.enforce_plan_limits(business_id)
    db.session.commit()

    db.session.refresh(held)
    db.session.refresh(empty_seller)
    assert held.is_active is True, 'stock the business is holding was switched off'
    assert empty_seller.is_active is False


def test_among_products_with_no_stock_the_fast_movers_win(register, make_product):
    """The second half of the rule. Nothing on the floor to protect, so what has
    actually sold decides - and it has to beat creation order, which is what the
    rule used to go on."""
    _client, business_id = register()
    stocked_fillers(make_product, business_id, 19)
    sold_well = make_product(business_id, sku='SOLD', name='Sells fast', stock=0)
    record_sales(business_id, sold_well, 900)
    # Created last, so it wins every tiebreak that is not about selling.
    dead = make_product(business_id, sku='DEAD', name='Never moved', stock=0)
    on_plan(business_id, 'free')

    limits.enforce_plan_limits(business_id)
    db.session.commit()

    db.session.refresh(sold_well)
    db.session.refresh(dead)
    assert sold_well.is_active is True, 'a proven seller lost to one that never sold'
    assert dead.is_active is False


def test_running_it_again_changes_nothing(big_shop):
    """It runs on every daily check, so it has to be a no-op once a business is
    inside its plan.

    This is also where "the choice does not reshuffle between runs" is
    covered. A separate test for that was written and then deleted: it could
    not be made to fail. The first run brings the count to exactly the cap,
    so the second finds nothing over it - the stability follows from
    enforcement only ever *removing* access, not from anything about the
    ordering.
    """
    _client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    assert limits.enforce_plan_limits(business_id) == {}


def test_upgrading_never_switches_anything_back_on(big_shop):
    """Deliberate. Only the owner knows which of the twenty-five they actually
    want back, and a product they retired on purpose must not reappear in their
    catalogue because they bought a bigger plan."""
    _client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    on_plan(business_id, 'advanced')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    assert active_products(business_id) == 20, 'products came back on their own'
    assert active_users(business_id) == 1, 'staff came back on their own'


# --- immediately, without waiting for a scheduled job ------------------------

def test_one_page_load_is_enough(big_shop):
    """The whole point of "immediate effect". The lifecycle job runs on a
    schedule a free instance cannot be relied on to keep, so using the app is
    what brings a business into line."""
    client, business_id = big_shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.paid_through = NOW - datetime.timedelta(days=60)
    db.session.commit()
    with client.session_transaction() as session:
        session.pop('subscription_checked', None)

    client.get('/')

    db.session.expire_all()
    assert Subscription.query.filter_by(business_id=business_id).one().plan.code == 'free'
    assert active_products(business_id) == 20
    assert active_users(business_id) == 1


def test_a_business_inside_its_plan_is_left_alone(big_shop):
    """A page load must not start switching things off for a paying customer."""
    client, business_id = big_shop
    with client.session_transaction() as session:
        session.pop('subscription_checked', None)

    client.get('/')

    assert active_products(business_id) == 25
    assert active_users(business_id) == 4


# --- and it says so ----------------------------------------------------------

def test_the_plans_choice_is_told_apart_from_the_owners(big_shop):
    """Both are is_active = false. Printing "locked by your plan - upgrade to
    unlock" over a line somebody deliberately stopped stocking would be a lie in
    the one place the app asks them for money."""
    client, business_id = big_shop
    retired = Product.query.filter_by(business_id=business_id, sku='P24').one()
    client.post('/products/deactivate/%d' % retired.id, follow_redirects=True)

    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    db.session.refresh(retired)
    assert retired.is_active is False
    assert retired.locked_by_plan is False, "the owner's own decision was relabelled"
    assert Product.query.filter_by(business_id=business_id,
                                   locked_by_plan=True).count() > 0


def test_the_catalogue_says_what_is_switched_off_and_offers_a_way_out(big_shop):
    client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    page = client.get('/products/').get_data(as_text=True)

    assert 'switched off by your plan' in page
    assert 'Kiosk covers 20 active products' in page


def test_the_billing_page_says_what_upgrading_would_give_back(big_shop):
    client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    page = client.get('/billing/').get_data(as_text=True)

    assert 'switched off by this plan' in page
    assert 'suspended' in page


def test_a_lapsed_paying_customer_is_told(big_shop):
    """They used to be told nothing at all. The trial banner is keyed to the
    trial date and times out after a fortnight, and the alerts inbox that
    carries subscription warnings is itself a paid feature - so falling to
    Kiosk removed the thing that would have explained falling to Kiosk."""
    client, business_id = big_shop
    db.session.add(PaymentTransaction(
        business_id=business_id, provider='momo', provider_ref='REF-1',
        amount_ghs=349, status='paid', period_start=NOW.date(),
        period_end=(NOW + datetime.timedelta(days=30)).date()))
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.trial_ends_at = NOW - datetime.timedelta(days=200)
    db.session.commit()
    on_plan(business_id, 'free', paid_through=-60)

    page = client.get('/').get_data(as_text=True)

    assert 'Your plan has lapsed' in page


def test_a_kiosk_business_that_never_paid_is_not_nagged_forever(big_shop):
    """The trial notice expires because it explains a past event. Somebody who
    arrived on Kiosk and stayed there has nothing to be told."""
    client, business_id = big_shop
    subscription = Subscription.query.filter_by(business_id=business_id).one()
    subscription.trial_ends_at = NOW - datetime.timedelta(days=200)
    db.session.commit()
    on_plan(business_id, 'free', paid_through=-60)

    page = client.get('/').get_data(as_text=True)

    assert 'Your plan has lapsed' not in page


# --- the way back in ---------------------------------------------------------

def test_staff_cannot_be_reinstated_past_the_seat_cap(big_shop):
    """Reactivating a *product* has always been limit-checked; reinstating a
    *person* was not. After a downgrade suspends people automatically, that gap
    would undo the enforcement one click at a time."""
    client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()

    suspended = User.query.filter_by(business_id=business_id, is_active=False).first()
    client.post('/auth/users/%d/toggle_active' % suspended.id, follow_redirects=True)

    db.session.refresh(suspended)
    assert suspended.is_active is False, 'a seat was reclaimed past the cap'


def test_after_upgrading_the_owner_can_switch_things_back_on(big_shop):
    """The way out has to actually work, or the upgrade prompt is a dead end."""
    client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()
    locked = Product.query.filter_by(business_id=business_id,
                                     locked_by_plan=True).first()

    on_plan(business_id, 'advanced')
    client.post('/products/deactivate/%d' % locked.id, follow_redirects=True)

    db.session.refresh(locked)
    assert locked.is_active is True
    assert locked.locked_by_plan is False, 'it still claims the plan is holding it'


def test_the_backup_remembers_why_a_product_is_off(big_shop):
    """The same column the backup dropped in W1, in a new coat. An archive that
    forgets this restores a catalogue where every plan-locked product looks like
    one the owner retired."""
    from services import backup

    spec = {name: columns for name, _model, columns in backup.EXPORT_SPEC}
    assert 'locked_by_plan' in spec['products']


# --- the cap has to hold on the page that spends the stock -------------------

def test_a_retired_product_cannot_be_sold(big_shop):
    """Found while recording the demo video: a product deactivated moments
    earlier was still listed in the sale form's picker.

    The form loaded every product the business had ever created. That is wrong
    on its own - an owner who retires a line does not expect to be offered it -
    and it quietly undid the plan enforcement above, because a business dropped
    to Kiosk could keep selling all four hundred products from this page. A cap
    the sell page ignores is not a cap.
    """
    client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()
    locked = Product.query.filter_by(business_id=business_id,
                                     locked_by_plan=True).first()

    page = client.get('/sales/add').get_data(as_text=True)

    assert 'value="%d"' % locked.id not in page, 'a switched-off product is on offer'


def test_a_posted_id_cannot_reach_a_retired_product(big_shop):
    """The choice list is a control, and a control is not a guarantee - the id
    arrives in a form. Same rule the unit and the price already follow here.

    **This needs two mutations to fail, recorded so neither guard is deleted as
    dead.** Filtering the choices makes WTForms refuse an id that is not on the
    list, and filtering the query refuses it again after that. Break either one
    alone and the other still holds; break both and a hand-posted id sells a
    product the plan switched off."""

    client, business_id = big_shop
    on_plan(business_id, 'free')
    limits.enforce_plan_limits(business_id)
    db.session.commit()
    locked = Product.query.filter_by(business_id=business_id,
                                     locked_by_plan=True).first()
    # Give it stock first. Enforcement retires the products with none, so
    # without this the sale is refused for being out of stock and the test
    # passes without ever exercising the active check - which is exactly what
    # it did on the first writing, green through every mutation of both guards.
    from purchases.models import StockBatch

    db.session.add(StockBatch(
        business_id=business_id, product_id=locked.id, batch_number='DEMO-1',
        quantity_received=50, quantity_remaining=50,
        received_date=datetime.date.today()))
    locked.quantity_in_stock = 50
    db.session.commit()
    before = Sale.query.filter_by(business_id=business_id).count()

    client.post('/sales/add', data={
        'sale_date': datetime.date.today().isoformat(), 'customer_id': '0',
        'items-0-product_id': str(locked.id), 'items-0-quantity': '1',
        'items-0-sell_unit': 'base', 'settlement': 'paid',
    }, follow_redirects=True)

    assert Sale.query.filter_by(business_id=business_id).count() == before, \
        'a hand-posted id sold a product the plan had switched off'
