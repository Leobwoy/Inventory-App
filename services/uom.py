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


def in_packs(product, base_quantity):
    """A stock figure in the unit the business counts in: '13 cartons + 6 bottles'.

    The remainder is kept rather than rounded, at the user's direction. A
    wholesaler genuinely holds part-cartons - a carton gets broken open the
    first time somebody buys three bottles - and rounding it away would put
    the books out and hide the stock that is actually loose on the floor.

    Short on purpose: this goes in table cells and badges. `describe` adds the
    base-unit total for the places that need to reconcile against a count.
    """
    base_quantity = int(base_quantity or 0)
    if not has_conversion(product):
        return quantity_label(product, base_quantity, BASE)

    whole, remainder = split(product, base_quantity)
    if whole and remainder:
        return (f'{quantity_label(product, whole, PURCHASE)} + '
                f'{quantity_label(product, remainder, BASE)}')
    if whole:
        return quantity_label(product, whole, PURCHASE)
    return quantity_label(product, remainder, BASE)


def describe(product, base_quantity):
    """As `in_packs`, plus the base-unit total: '10 cartons + 6 pcs (246 pcs)'.

    For the places that have to reconcile against a physical count, where the
    number of individual items is the thing being checked.
    """
    base_quantity = int(base_quantity or 0)
    if not has_conversion(product):
        return quantity_label(product, base_quantity, BASE)

    whole, _remainder = split(product, base_quantity)
    if not whole:
        return quantity_label(product, base_quantity, BASE)
    return (f'{in_packs(product, base_quantity)} '
            f'({quantity_label(product, base_quantity, BASE)})')


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


def plural(word):
    """A unit word for more than one of it.

    These are words the business typed, so they are whatever they are: "pcs",
    "box", "crate". Appending a bare "s" produced "pcss" and "boxs", and "pcs"
    is the default base unit, so that was the common case rather than an edge
    one. Lives here because this module owns what a unit is called; the same
    three lines run in the browser on the product and purchase order forms.
    """
    word = (word or '').strip()
    if not word or word.lower().endswith('s'):
        return word
    if word.lower().endswith(('x', 'z', 'ch', 'sh')):
        return word + 'es'
    return word + 's'


def packing(product):
    """How this product is packed, in one phrase: 'carton of 24', or 'bottle'.

    For the column that has to say what unit the numbers beside it are in. A
    spreadsheet cannot hold "13 cartons + 6 bottles" in a cell somebody sums,
    so exports name the unit once and keep every figure numeric.
    """
    if not has_conversion(product):
        return unit_label(product, BASE)
    return f'{unit_label(product, PURCHASE)} of {factor(product)}'


def quantity_label(product, count, unit=BASE):
    """A quantity as it should be printed: "2 cartons", "1 carton", "48 pcs"."""
    count = int(count or 0)
    word = unit_label(product, unit)
    return f'{count} {word if count == 1 else plural(word)}'


def price_to_base(product, price, unit=BASE):
    """A price for one sold unit, expressed per base unit.

    Six decimals when it is derived, for the reason F-41 established on the buy
    side and which bites harder here: a carton at 1,000 for 24 is 41.666... a
    bottle, and rounding that to 41.67 bills 2,000.16 for the 48 bottles the
    customer agreed 2,000.00 for. A price typed directly in base units is
    already exact and stays at 2dp.
    """
    price = Decimal(str(price or 0))
    if unit != PURCHASE or not has_conversion(product):
        return price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return (price / Decimal(factor(product))).quantize(
        Decimal('0.000001'), rounding=ROUND_HALF_UP)
