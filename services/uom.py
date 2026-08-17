"""Converting between how stock is bought and how it is sold.

A wholesaler buys a crate of Coca-Cola - 24 bottles, priced per crate - and sells
single bottles. Product already carried base_uom, purchase_uom and
units_per_purchase_uom since the variant restructure, and nothing ever read them,
so the arithmetic was left to the person at the keyboard on every purchase order.

One rule holds everything together: **everything is stored in base units.**
Stock, sale lines, purchase order lines and unit costs are all in pieces. The
purchase unit exists only at the edges - what someone types in, and what they
read back. Storing two units would mean every query had to know which one it was
looking at, which is how stock figures start disagreeing with each other.

That was written before anything could be *sold* by the carton, and it described
an accident as an invariant: sale lines were in base units because there was no
other option, not because anything enforced it. Selling by the pack now goes
through `to_base` like buying always did, so the rule is true on purpose.
"""
from decimal import Decimal, ROUND_HALF_UP

BASE = 'base'
PURCHASE = 'purchase'


def factor(product):
    """How many base units make one purchase unit. Never less than 1."""
    return max(1, int(product.units_per_purchase_uom or 1))


def has_conversion(product):
    """True when buying and selling genuinely use different units.

    A product bought and sold in pieces needs none of this, and showing it a
    carton/piece selector would be noise.
    """
    return (
        factor(product) > 1
        and (product.purchase_uom or '').strip().lower() != (product.base_uom or '').strip().lower()
    )


def has_conversion_available(products):
    """True if any product in the list buys and sells in different units.

    Used to decide whether the unit selector is worth showing at all - a
    business that deals only in single units should not see it.
    """
    return any(has_conversion(p) for p in products)


def to_base(product, quantity, unit=BASE):
    """Convert a typed quantity into base units.

    Checks `has_conversion` itself rather than trusting the caller to have done
    it. It multiplied on `factor()` alone before, so a product with the same
    name for both units and a stray count of 12 would be multiplied by 12 - safe
    only because both call sites happened to guard first. Safety that lives in
    the callers is safety that lasts until the third caller.
    """
    quantity = int(quantity or 0)
    if unit != PURCHASE or not has_conversion(product):
        return quantity
    return quantity * factor(product)


def split(product, base_quantity):
    """Base units as (whole purchase units, leftover base units).

    240 pieces at 24 per carton is (10, 0); 250 is (10, 10). The remainder is
    kept rather than rounded because a wholesaler genuinely does hold part-crates,
    and rounding it away would put the books out.
    """
    base_quantity = int(base_quantity or 0)
    per = factor(product)
    return divmod(base_quantity, per)


def describe(product, base_quantity):
    """Human-readable quantity, e.g. '10 cartons + 6 pcs (246 pcs)'."""
    base_quantity = int(base_quantity or 0)
    base_unit = product.base_uom or 'pcs'
    if not has_conversion(product):
        return f'{base_quantity} {base_unit}'

    whole, remainder = split(product, base_quantity)
    purchase_unit = product.purchase_uom or 'unit'
    if whole and remainder:
        return f'{whole} {purchase_unit} + {remainder} {base_unit} ({base_quantity} {base_unit})'
    if whole:
        return f'{whole} {purchase_unit} ({base_quantity} {base_unit})'
    return f'{base_quantity} {base_unit}'


def cost_to_base(product, cost, unit=BASE):
    """Convert a typed unit cost into cost per base unit.

    A crate at GHS 48 for 24 bottles is GHS 2.00 a bottle.

    The converted figure keeps six decimals, because it is derived rather than
    typed: GHS 1.00 for 24 rounds to 0.04 at pesewa precision, and 100 cartons
    then record 96.00 against 100.00 actually paid. It is also the cost price
    behind every margin and the number services/sourcing.py compares suppliers
    on, so the error lands in the one feature meant to answer who is cheaper.

    A cost typed directly in base units is already exact and stays at 2dp -
    widening it would only invent precision nobody entered. Display quantises
    to 2dp everywhere; this is the stored intermediate (F-41).
    """
    cost = Decimal(str(cost or 0))
    if unit != PURCHASE or not has_conversion(product):
        return cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return (cost / Decimal(factor(product))).quantize(
        Decimal('0.000001'), rounding=ROUND_HALF_UP)


def cost_per_purchase_unit(product, base_cost):
    """The inverse, for showing a per-crate figure next to a per-bottle one."""
    return (Decimal(str(base_cost or 0)) * Decimal(factor(product))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)


def sell_units(product):
    """The units this product may be sold in, most likely first.

    A product with no real conversion has exactly one answer whatever
    `sell_unit` says, because a "carton" the same size as a piece is not a
    choice - it is two names for the same thing.
    """
    if not has_conversion(product):
        return [BASE]
    choice = (product.sell_unit or BASE).strip().lower()
    if choice == PURCHASE:
        return [PURCHASE]
    if choice == 'both':
        return [PURCHASE, BASE]
    return [BASE]


def default_sell_unit(product):
    """What the sale form should start on."""
    return sell_units(product)[0]


def price_for(product, unit=BASE):
    """What one of `unit` lists for.

    A pack price is stored, never derived, when the business has set one: the
    whole point of a case is that it costs less per bottle than the bottles do
    singly, and no arithmetic on the single price can produce that number. When
    none is set a pack really is count x the single price, which is what every
    product meant before there was anywhere to put a pack price.
    """
    single = Decimal(str(product.unit_price or 0))
    if unit != PURCHASE or not has_conversion(product):
        return single.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if product.pack_price is not None:
        return Decimal(str(product.pack_price)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
    return (single * Decimal(factor(product))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)


def per_base_price(product):
    """What one piece works out at when bought by the pack.

    Shown on the product form beside the pack price, never typed. This is the
    figure that makes a carton price typed into the singles box obvious before
    it is saved rather than weeks afterwards.
    """
    if not has_conversion(product) or product.pack_price is None:
        return Decimal(str(product.unit_price or 0)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
    return (Decimal(str(product.pack_price)) / Decimal(factor(product))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)


def unit_label(product, unit=BASE):
    """What to call one of `unit` on screen."""
    if unit == PURCHASE and has_conversion(product):
        return product.purchase_uom or 'unit'
    return product.base_uom or 'pcs'
