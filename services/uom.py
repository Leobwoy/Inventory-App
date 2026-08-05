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
    """Convert a typed quantity into base units."""
    quantity = int(quantity or 0)
    return quantity * factor(product) if unit == PURCHASE else quantity


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
    if unit != PURCHASE:
        return cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return (cost / Decimal(factor(product))).quantize(
        Decimal('0.000001'), rounding=ROUND_HALF_UP)


def cost_per_purchase_unit(product, base_cost):
    """The inverse, for showing a per-crate figure next to a per-bottle one."""
    return (Decimal(str(base_cost or 0)) * Decimal(factor(product))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)
