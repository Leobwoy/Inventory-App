"""Sale price resolution.

price_at_sale used to be written straight from submitted form data. The template
marked the field readonly, but readonly is a rendering hint - the value still
posts, so a modified request could carry any price including zero or below cost,
and no existing report would have shown it (F-07).

The server now decides the price. A submitted value is treated as a *request*,
honoured only when policy allows, and any deviation from list is audited.
"""
from decimal import Decimal

from services import uom

from services import audit


class PriceRejected(Exception):
    """A requested price is outside what policy permits."""


def resolve(product, business, requested_price, may_discount, unit=uom.BASE):
    """Return the price to charge for `product`.

    - No request, or a request at list price -> list price.
    - Above list -> allowed (it costs the business nothing) but audited, since an
      unintended overcharge is worth being able to find later.
    - Below list -> requires the sales.discount permission, must stay within the
      business's max_discount_percent, and may never go below cost.

    Raises PriceRejected with a message meant for the person on the till.
    """
    # The list price of the unit being sold, not always the single price. A
    # carton has its own, which is the whole point of buying one, so a discount
    # ceiling has to be measured against the carton a wholesaler negotiated over
    # rather than against 24 times a bottle.
    list_price = uom.price_for(product, unit)

    if requested_price is None:
        return list_price, None

    requested = Decimal(requested_price)
    # The standard in code-standards.md, which this function did not follow
    # while api/routes.py did. NumberRange(min=0) has no max, so Decimal('Infinity')
    # reaches here and comes back out as the charged price.
    if not requested.is_finite():
        raise PriceRejected('That is not a price.')
    if requested < 0:
        raise PriceRejected('Price cannot be negative.')

    if requested == list_price:
        return list_price, None

    if requested > list_price:
        return requested, {
            'kind': 'above_list',
            'list_price': str(list_price),
            'charged': str(requested),
        }

    # --- below list from here ---
    if not may_discount:
        raise PriceRejected(
            f'{product.name} is priced at {list_price}. You do not have permission '
            'to sell below the listed price.'
        )

    ceiling = Decimal(getattr(business, 'max_discount_percent', 0) or 0)
    if ceiling <= 0:
        raise PriceRejected(
            f'{product.name}: discounts are switched off for this business. '
            'An Owner can allow them in business settings.'
        )

    floor_by_policy = (list_price * (Decimal(100) - ceiling) / Decimal(100)).quantize(Decimal('0.01'))
    if requested < floor_by_policy:
        raise PriceRejected(
            f'{product.name}: {ceiling}% is the most that may be discounted, '
            f'so the lowest allowed price is {floor_by_policy}.'
        )

    # Cost is stored per base unit, and `requested` is per unit *sold*. Comparing
    # them directly would measure a carton price against a bottle's cost, so a
    # carton costing 921.60 would pass the floor at 500.
    cost = Decimal(product.cost_price or 0)
    if unit == uom.PURCHASE and uom.has_conversion(product):
        cost = uom.cost_per_purchase_unit(product, cost)
    # cost 0 means nobody has recorded it yet (staff without cost visibility can
    # create products), so there is no meaningful floor to enforce.
    if cost > 0 and requested < cost:
        raise PriceRejected(f'{product.name} cannot be sold below cost.')

    discount_pct = ((list_price - requested) / list_price * 100).quantize(Decimal('0.01')) \
        if list_price > 0 else Decimal(0)
    return requested, {
        'kind': 'discount',
        'list_price': str(list_price),
        'charged': str(requested),
        'discount_percent': str(discount_pct),
    }


def record_deviation(sale, product, deviation):
    """Audit a sale line priced away from list."""
    if not deviation:
        return
    audit.log(
        'sale.price_override',
        entity_type='sale',
        entity_id=sale.id,
        product_id=product.id,
        product_sku=product.sku,
        **deviation,
    )
