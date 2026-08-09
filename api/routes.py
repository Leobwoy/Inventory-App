"""JSON endpoints for the offline queue.

This is the application's first API surface, and it exists for exactly one
client: the service worker syncing sales recorded without a signal.

It calls the same services the web forms call. That is the whole point of
having them. A second implementation of "how much stock is there" or "may this
price be charged" would drift from the first within weeks, and the copy that
drifted would be the one running when the shop had no network - the case nobody
tests by hand.

Three rules shape the sync:

1. **Idempotent.** A sync that times out after the server committed is
   indistinguishable from one that failed, so the device retries. The sale
   carries an id the device generated, and a retry returns the original.
2. **The server re-decides everything.** Stock and price are checked again at
   sync time against the truth now, not the truth the device had when it was
   offline.
3. **A conflict is reported, never resolved quietly.** Two tills selling the
   last crate is a real event with a real answer, and the answer belongs to the
   person who knows what is on the floor - not to a rule invented here.
"""
import datetime
from decimal import Decimal, InvalidOperation

from flask import abort, current_app, jsonify, request
from flask_login import current_user, login_required

from api import api_bp
from auth.decorators import permission_required, requires_feature
from credit.models import Payment, sale_total
from extensions import db
from products.models import Product
from sales.models import Customer, Sale, SaleItem
from services import audit, pricing, stock

# One sync carries a shop's backlog, not its history. A device that has been
# offline for a week still syncs, in batches.
MAX_BATCH = 50


@api_bp.after_request
def never_cache(response):
    """No API response may be stored.

    /session hands out a CSRF token and names the user and business; /catalogue
    carries customer names and phone numbers. Both are scoped to whoever is
    signed in, and neither carries a cache header of its own - so a shared
    device could serve one person's data to the next.
    """
    response.headers['Cache-Control'] = 'no-store'
    return response


@api_bp.route('/cron/subscriptions', methods=['POST'])
def cron_subscriptions():
    """Apply every due subscription transition. For a scheduler, not a person.

    Guarded by a shared secret in a header rather than a login, because the
    caller is a cron service with no session. Unset secret means 404: an
    unconfigured endpoint should not exist, and 404 does not advertise that it
    might.

    Deliberately reachable without authentication *and* CSRF-exempt, which is
    only safe because it takes no input, is idempotent, and does nothing a
    signed-in user could not already cause by loading a page.
    """
    import hmac
    import os

    from services import subscriptions

    expected = os.environ.get('CRON_SECRET', '').strip()
    supplied = (request.headers.get('X-Cron-Key') or '').strip()
    # Constant time: a plain == leaks the secret one character at a time to
    # anyone patient enough to measure.
    #
    # Compared as bytes, because compare_digest refuses two strings when either
    # holds a non-ASCII character - and a secret someone generated with a
    # passphrase rather than token_urlsafe would then raise, turning the guard
    # into a 500 that reveals the endpoint is real.
    if not expected or not hmac.compare_digest(expected.encode('utf-8'),
                                               supplied.encode('utf-8')):
        abort(404)

    summary = subscriptions.reconcile_all()
    if summary['moved'] or summary['failed']:
        current_app.logger.info('subscription reconcile: %s', summary)
    return jsonify(summary)


@api_bp.route('/session')
@login_required
def session_state():
    """A fresh CSRF token, and confirmation the session is still good.

    CSRF tokens expire after an hour. A sale queued at dawn and synced at noon
    would fail on a token minted with the page, and the failure would look
    exactly like a rejected sale. The device asks for a new one immediately
    before syncing, when it is online by definition.
    """
    from flask_wtf.csrf import generate_csrf
    from services.limits import has_feature

    return jsonify({
        'csrf_token': generate_csrf(),
        'user': current_user.name,
        'business': current_user.business.name,
        'offline_enabled': has_feature('offline'),
        'may_sell': current_user.can('sales.create'),
    })


@api_bp.route('/catalogue')
@login_required
@permission_required('products.view')
@requires_feature('offline')
def catalogue():
    """What the device needs to sell without a network.

    Deliberately narrow: name, price, stock and unit. No cost prices - the
    device cache is readable by anyone who picks the phone up, and cost is
    gated everywhere else (F-16). It would be careless to post it here.
    """
    products = (Product.query
                .filter_by(business_id=current_user.business_id, is_active=True)
                .order_by(Product.name)
                .all())
    return jsonify({
        'fetched_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'max_discount_percent': str(current_user.business.max_discount_percent or 0),
        'may_discount': current_user.can('sales.discount'),
        'products': [{
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'unit_price': str(p.unit_price or 0),
            'quantity_in_stock': p.quantity_in_stock or 0,
            'base_uom': p.base_uom,
        } for p in products],
        'customers': [{'id': c.id, 'name': c.name, 'phone': c.phone}
                      for c in Customer.query
                      .filter_by(business_id=current_user.business_id)
                      .order_by(Customer.name).all()],
    })


def _result(client_id, status, **extra):
    return dict(client_id=client_id, status=status, **extra)


def _record_one(payload, business_id):
    """Write one queued sale. Returns a result dict; never raises.

    Each sale is its own transaction. One rejected line in a backlog of twenty
    must not roll back the nineteen that were fine, and must not stop the rest
    being tried.
    """
    client_id = (payload.get('client_id') or '').strip()
    if not client_id:
        return _result(None, 'rejected', message='Sale has no client id.')

    existing = Sale.query.filter_by(business_id=business_id, client_id=client_id).first()
    if existing:
        # A retry after a timeout, not a second sale.
        return _result(client_id, 'accepted', sale_id=existing.id, duplicate=True)

    lines = payload.get('items') or []
    if not lines:
        return _result(client_id, 'rejected', message='Sale has no items.')

    try:
        sale_date = datetime.date.fromisoformat(payload.get('sale_date'))
    except (TypeError, ValueError):
        return _result(client_id, 'rejected', message='Sale has no valid date.')
    if sale_date > datetime.date.today():
        return _result(client_id, 'rejected', message='Sale is dated in the future.')

    customer_id = payload.get('customer_id')
    if customer_id:
        # Never trust a posted foreign key - resolve it inside the business.
        customer = Customer.query.filter_by(id=customer_id, business_id=business_id).first()
        if not customer:
            return _result(client_id, 'rejected', message='That customer no longer exists.')
    else:
        customer_id = None

    try:
        sale = Sale(
            business_id=business_id,
            sale_date=sale_date,
            customer_id=customer_id,
            customer_name=None if customer_id else (payload.get('customer_name') or None),
            customer_phone=None if customer_id else (payload.get('customer_phone') or None),
            client_id=client_id,
        )
        db.session.add(sale)

        deviations = []
        for line in lines:
            product = Product.query.filter_by(
                id=line.get('product_id'), business_id=business_id).first()
            if not product:
                raise _Conflict('A product on this sale no longer exists.')

            # Unreadable is rejected, not retried. A malformed value fails the
            # same way every time, and 'retry' would leave it in the device queue
            # forever, failing on every reconnect with nobody told why.
            try:
                quantity = int(line.get('quantity') or 0)
            except (TypeError, ValueError):
                raise _Rejected('A line has an unreadable quantity.') from None
            if quantity <= 0:
                raise _Rejected('A line has no quantity.')

            requested = line.get('price')
            try:
                requested = Decimal(str(requested)) if requested is not None else None
            except (InvalidOperation, ValueError):
                raise _Rejected('A line has an unreadable price.') from None
            # Decimal() accepts 'NaN' and 'Infinity' without complaint. NaN
            # poisons every comparison downstream; Infinity would sail through
            # the discount floor as though it were the highest price ever
            # charged. Neither is a price.
            if requested is not None and not requested.is_finite():
                raise _Rejected('A line has an unreadable price.')

            # The price the device saw may be stale, and the rule may have
            # changed while it was offline. Re-resolve against the truth now.
            charged, deviation = pricing.resolve(
                product=product,
                business=current_user.business,
                requested_price=requested,
                may_discount=current_user.can('sales.discount'),
            )

            item = SaleItem(product_id=product.id, quantity=quantity,
                            price_at_sale=charged,
                            list_price=Decimal(product.unit_price or 0))
            sale.items.append(item)
            if deviation:
                deviations.append((product, deviation))

            # Same FEFO path as the web form, row locks and all - which is what
            # makes two devices selling the last crate resolve correctly.
            stock.deduct_fefo(product, quantity, business_id)

        db.session.flush()

        try:
            received = Decimal(str(payload.get('amount_paid') or 0))
        except (InvalidOperation, ValueError):
            raise _Rejected('The amount paid is unreadable.') from None
        # Infinity here is the dangerous one: min(received, total) clamps it to
        # the full amount, so a malformed payload would record a sale as paid
        # in full when nothing was received.
        if not received.is_finite():
            raise _Rejected('The amount paid is unreadable.')
        total = sale_total(sale)
        received = max(Decimal('0'), min(received, total))
        if received > 0:
            db.session.add(Payment(
                business_id=business_id, sale_id=sale.id, customer_id=sale.customer_id,
                amount=received, method=payload.get('payment_method') or 'cash',
                reference=(payload.get('payment_reference') or '').strip() or None,
                paid_on=sale_date, recorded_by=current_user.id,
            ))

        audit.log('sale.synced', entity_type='sale', entity_id=sale.id,
                  client_id=client_id, total=str(total), paid=str(received),
                  recorded_offline_at=payload.get('recorded_at'))
        for product, deviation in deviations:
            audit.log('sale.price_deviation', entity_type='product',
                      entity_id=product.id, sale_id=sale.id, **deviation)

        db.session.commit()
        return _result(client_id, 'accepted', sale_id=sale.id,
                       total=str(total), owing=str(total - received))

    except stock.InsufficientStock as e:
        db.session.rollback()
        # The commonest conflict: sold on two devices, or sold in the shop while
        # this one was offline. The user has to decide, so say what happened in
        # the numbers they can check against the floor.
        return _result(client_id, 'conflict', reason='stock',
                       message=str(e), product=e.product.name,
                       wanted=e.requested, available=e.available)
    except pricing.PriceRejected as e:
        db.session.rollback()
        return _result(client_id, 'conflict', reason='price', message=str(e))
    except _Conflict as e:
        db.session.rollback()
        return _result(client_id, 'conflict', reason='missing', message=str(e))
    except _Rejected as e:
        db.session.rollback()
        return _result(client_id, 'rejected', message=str(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception('syncing a queued sale failed')
        # Deliberately not 'rejected': the device must keep this one and try
        # again. Discarding a sale because the server had a bad moment loses
        # real money and nobody would ever know it happened.
        return _result(client_id, 'retry',
                       message='Could not record this sale. It will be tried again.')


class _Conflict(Exception):
    """Something the sale depends on is gone. Needs a human."""


class _Rejected(Exception):
    """The sale itself is malformed. Retrying will not help."""


@api_bp.route('/sales', methods=['POST'])
@login_required
@permission_required('sales.create')
@requires_feature('offline')
def sync_sales():
    """Accept a batch of sales recorded offline.

    Always 200 with a per-sale verdict, even when every one of them failed. A
    blanket error code would tell the device nothing about which sales to keep,
    which to retry and which to show someone.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('sales'), list):
        return jsonify({'error': 'Expected {"sales": [...]}.'}), 400

    queued = payload['sales']
    if len(queued) > MAX_BATCH:
        return jsonify({'error': f'Send at most {MAX_BATCH} sales at a time.',
                        'max_batch': MAX_BATCH}), 400

    results = [_record_one(sale, current_user.business_id) for sale in queued]
    return jsonify({
        'results': results,
        'accepted': sum(1 for r in results if r['status'] == 'accepted'),
        'conflicts': sum(1 for r in results if r['status'] == 'conflict'),
    })
