from flask import render_template, redirect, url_for, flash, request, current_app
from . import products_bp
from .models import Product, Category, Supplier, Brand, ItemGroup
from .forms import ProductForm, ProductUploadForm, CategoryForm, SupplierForm, BrandForm, ItemGroupForm
from extensions import db
from werkzeug.utils import secure_filename
import openpyxl
import os
import re
import tempfile
from decimal import Decimal, InvalidOperation
import pandas as pd
from flask import send_file
import io
from flask_login import login_required, current_user
from auth.decorators import permission_required
from datetime import date, timedelta
from purchases.models import PurchaseOrder, StockBatch
from services import audit, limits, listing, uom

PRODUCT_SORTS = {
    'name':     [Product.name.asc()],
    'newest':   [Product.id.desc()],
    'stock_low': [Product.quantity_in_stock.asc(), Product.name.asc()],
    'stock_high': [Product.quantity_in_stock.desc(), Product.name.asc()],
    'price_low': [Product.unit_price.asc(), Product.name.asc()],
    'price_high': [Product.unit_price.desc(), Product.name.asc()],
}
PRODUCT_SORT_LABELS = [
    ('name', 'Name (A–Z)'), ('newest', 'Recently added'),
    ('stock_low', 'Stock: lowest'), ('stock_high', 'Stock: highest'),
    ('price_low', 'Price: lowest'), ('price_high', 'Price: highest'),
]

SUPPLIER_SORTS = {
    'name':   [Supplier.name.asc()],
    'newest': [Supplier.id.desc()],
}
SUPPLIER_SORT_LABELS = [('name', 'Name (A-Z)'), ('newest', 'Recently added')]


@products_bp.route('/')
@login_required
@permission_required('products.view')
def list_products():
    page = request.args.get('page', 1, type=int)
    business_id = current_user.business_id
    term = listing.search_term()
    stock_filter = listing.filter_value('stock', ['low', 'out', 'expiring'])
    status = listing.filter_value('status', ['active', 'inactive'])
    sort = listing.sort_key(PRODUCT_SORTS, 'name')

    query = Product.query.filter_by(business_id=business_id)
    query = listing.apply_search(query, term, [
        Product.name, Product.sku, Product.barcode, Product.variant_label,
    ])

    if status == 'active':
        query = query.filter(Product.is_active.is_(True))
    elif status == 'inactive':
        query = query.filter(Product.is_active.is_(False))

    if stock_filter == 'out':
        query = query.filter(Product.quantity_in_stock <= 0)
    elif stock_filter == 'low':
        # At or below the threshold is what the owner needs to reorder, and a
        # product already at zero is the most urgent case of that.
        query = query.filter(Product.quantity_in_stock <= Product.min_stock_alert)
    elif stock_filter == 'expiring':
        # Restricted to groups that opted in, so this matches what the expiry
        # alert counts. A filter that disagrees with the alert linking to it is
        # worse than no filter.
        horizon = date.today() + timedelta(days=current_user.business.expiry_alert_days or 30)
        expiring = (db.session.query(StockBatch.product_id)
                    .join(Product, Product.id == StockBatch.product_id)
                    .join(ItemGroup, ItemGroup.id == Product.item_group_id)
                    .filter(StockBatch.business_id == business_id,
                            StockBatch.quantity_remaining > 0,
                            StockBatch.expiry_date.isnot(None),
                            StockBatch.expiry_date <= horizon,
                            ItemGroup.track_expiry.is_(True)))
        query = query.filter(Product.id.in_(expiring))

    query = listing.apply_sort(query, PRODUCT_SORTS, sort)
    pagination = query.paginate(page=page, per_page=15, error_out=False)
    return render_template(
        'products/list.html', products=pagination.items, pagination=pagination,
        search_query=term, q=term, sort=sort, sort_options=PRODUCT_SORT_LABELS,
        stock=stock_filter, status=status,
        is_filtered=listing.is_filtered('q', 'stock', 'status'))

@products_bp.route('/alerts')
@login_required
@permission_required('products.view')
def alerts():
    """Everything needing attention, worst first.

    Lives under products because stock is most of it, but it deliberately spans
    modules - the question is "what needs me today", and that does not sort
    itself by which part of the app produced it.
    """
    from services import notifications

    return render_template('products/alerts.html',
                           alerts=notifications.for_user(current_user))


@products_bp.route('/low-stock')
@login_required
@permission_required('products.view')
def low_stock():
    """What needs reordering, worst first. Empties itself.

    Nothing is stored, so a product leaves this page the moment stock goes back
    above its reorder level — there is no "mark as handled", because handling it
    *is* receiving the stock.

    Includes products at zero, deliberately. The alerts page keeps low and empty
    apart because one is a warning and the other is already costing money, but
    the question *this* page answers is "what do I buy", and an item at zero is
    the most urgent answer to it.
    """
    products = (Product.query
                .filter(Product.business_id == current_user.business_id,
                        Product.is_active.is_(True),
                        Product.quantity_in_stock <= Product.min_stock_alert)
                .order_by(Product.quantity_in_stock.asc(), Product.name)
                .all())
    return render_template('products/low_stock.html', products=products)


@products_bp.route('/alerts/count')
@login_required
@permission_required('products.view')
def alert_count():
    """How many things need attention, for the badge.

    A separate request rather than a context processor. Working this out costs
    several queries, and the sidebar renders on all fifty-odd routes - so as a
    context processor it would put that cost on every page in the app to
    populate a number most of them never show. Fetched after load instead, so
    page renders stay exactly as expensive as they were.
    """
    from flask import jsonify
    from services import notifications

    # for_user, not cached_for: the badge must count what this person will
    # actually be shown, or it advertises alerts the page then withholds.
    alerts = notifications.for_user(current_user)
    response = jsonify({
        'count': len(alerts),
        'critical': sum(1 for a in alerts if a['severity'] == 'critical'),
    })
    # Never stored: it is a live figure, and a cached one is worse than none.
    response.headers['Cache-Control'] = 'no-store'
    return response


def _sku_token(text, length=4):
    """Uppercase alphanumeric fragment of `text`, for building a readable SKU."""
    return re.sub(r'[^A-Z0-9]', '', (text or '').upper())[:length]


def generate_sku(brand, item_group, variant_label=None, business_id=None):
    """Build a {brand}-{itemgroup}-{variant} SKU, suffixed until it is unique.

    Scoped to one business: SKUs are unique per tenant, so two businesses may
    each hold the same code without colliding (F-17).
    """
    business_id = business_id or current_user.business_id
    parts = [_sku_token(brand.name if brand else ''), _sku_token(item_group.name if item_group else '')]
    if variant_label:
        parts.append(_sku_token(variant_label, 6))
    base = '-'.join(p for p in parts if p) or 'SKU'
    candidate, n = base, 1
    while Product.query.filter_by(sku=candidate, business_id=business_id).first():
        n += 1
        candidate = f'{base}-{n}'
    return candidate[:50]


def _strip_cost_price(form):
    """Remove the cost fields from a form when the user may not see them.

    Deleting the bound fields, rather than just hiding them in the template,
    means validation does not demand a value the user was never shown, and a
    value posted by hand is ignored rather than saved. Both boxes go: the pack
    cost is the same secret as the single cost, just multiplied by 24.
    """
    if not current_user.can('products.cost_price.view'):
        del form.cost_price
        del form.pack_cost
        return False
    return True


def _history_blocking_delete(product):
    """Describe why a product cannot be deleted, or None if it can.

    StockBatch.product_id, SaleItem.product_id and PurchaseOrderItem.product_id
    are all NOT NULL, so deleting a product that has any of them raises a
    constraint violation as SQLAlchemy tries to null the foreign keys - a 500
    with no explanation. Beyond the crash, deleting a product that has traded
    would erase the history behind every report that mentions it.
    """
    from sales.models import SaleItem
    from purchases.models import PurchaseOrderItem, StockBatch

    reasons = []
    if StockBatch.query.filter_by(product_id=product.id).count():
        reasons.append('stock history')
    if SaleItem.query.filter_by(product_id=product.id).count():
        reasons.append('recorded sales')
    if PurchaseOrderItem.query.filter_by(product_id=product.id).count():
        reasons.append('purchase orders')

    if not reasons:
        return None
    if len(reasons) == 1:
        return reasons[0]
    return ', '.join(reasons[:-1]) + ' and ' + reasons[-1]


def _scoped_catalogue(form):
    """Resolve brand/item group/category from the form, scoped to the caller's business.

    Returns (brand, item_group, category). Brand and item group are None when the
    submitted id does not belong to this business - never trust a posted foreign key.
    """
    biz = current_user.business_id
    brand = Brand.query.filter_by(id=form.brand_id.data, business_id=biz).first()
    item_group = ItemGroup.query.filter_by(id=form.item_group_id.data, business_id=biz).first()
    category = None
    if form.category_id.data:
        category = Category.query.filter_by(id=form.category_id.data, business_id=biz).first()
    return brand, item_group, category


def _sell_unit_for(form):
    """What the product may be rung up in, given what was actually entered.

    A pack of one is not a pack. Without a real conversion the only honest
    answer is singles, whatever the dropdown said - otherwise the sale form
    offers a carton the server then refuses, which reads as the app being
    broken rather than the product being set up wrong.
    """
    if not form.has_pack():
        return 'base'
    return form.sell_unit.data or 'base'


def _apply_prices(form, product, may_see_cost):
    """Write the stored per-single prices from whatever was typed.

    The carton is the unit now. A wholesaler buys, sells and quotes by the
    carton, so that is the only price the form asks for, and `unit_price` and
    `cost_price` - which stay stored, stay NOT NULL and are still what every
    query, sort and export reads - are derived here.

    Deriving rather than dropping the per-single columns is deliberate. Making
    them nullable would push a NULL into price sorting (`PRODUCT_SORTS` above,
    where it sorts unpredictably on Postgres), into the offline catalogue
    payload, and into every report that multiplies by them.
    """
    if not form.has_pack():
        product.unit_price = form.unit_price.data
        if may_see_cost:
            product.cost_price = form.cost_price.data
        return

    # per_base_price and cost_to_base both read the product, so the pack fields
    # must already be on it. Both are set above every call site here.
    product.unit_price = uom.per_base_price(product)
    if may_see_cost:
        # Six decimals, and the column was widened to hold them. At two the
        # round trip drifts: a carton at 1,000 for 24 stores 41.67 a bottle,
        # which reads back as a carton costing 1,000.08, and every edit of the
        # product would nudge it again.
        product.cost_price = uom.cost_to_base(product, form.pack_cost.data, uom.PURCHASE)


def _min_stock_base(form):
    """The low-stock threshold in base units, from a figure typed in packs."""
    typed = form.min_stock_alert.data or 0
    if not form.has_pack():
        return typed
    return typed * (form.units_per_purchase_uom.data or 1)


def _min_stock_packs(product):
    """The stored threshold as a figure to type back into the form.

    Rounded up, not down. This is the level that triggers a warning, so the
    error that costs something is warning too late. Rounding up is also stable:
    100 base units at 24 a carton shows 5, saves 120, and shows 5 again -
    rounding down would show 4, save 96, and walk the threshold downwards every
    time the product was opened.
    """
    if not uom.has_conversion(product):
        return product.min_stock_alert or 0
    per = uom.factor(product)
    return -(-(product.min_stock_alert or 0) // per)


@products_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('products.create')
def add_product():
    form = ProductForm()
    may_see_cost = _strip_cost_price(form)
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    form.brand_id.choices = [(b.id, b.name) for b in Brand.query.filter_by(business_id=current_user.business_id).order_by(Brand.name)]
    form.item_group_id.choices = [(i.id, i.name) for i in ItemGroup.query.filter_by(business_id=current_user.business_id).order_by(ItemGroup.name)]

    # Do not allow modifying quantity during creation; handled via PO/StockBatch
    if request.method == 'GET':
        form.quantity_in_stock.data = 0

    if form.validate_on_submit():
        allowed, message = limits.can_add_product()
        if not allowed:
            flash(message, 'warning')
            return render_template('products/add_edit.html', form=form, action='Add')

        brand, item_group, category = _scoped_catalogue(form)
        if not brand or not item_group:
            flash('Select a valid brand and item group.', 'danger')
            return render_template('products/add_edit.html', form=form, action='Add')

        base_uom = (form.base_uom.data or 'pcs').strip()
        product = Product(
            business_id=current_user.business_id,
            name=form.name.data,
            sku=(form.sku.data or '').strip() or generate_sku(brand, item_group, form.variant_label.data),
            barcode=form.barcode.data,
            description=form.description.data,
            # Staff without cost visibility create the product at zero cost; an
            # Owner or Manager fills it in later. Never inferred from sale price,
            # which would fabricate a margin.
            cost_price=0,
            unit_price=0,
            quantity_in_stock=0, # Initialized to 0, managed via StockBatch
            min_stock_alert=_min_stock_base(form),
            category=category,
            brand_id=brand.id,
            item_group_id=item_group.id,
            variant_label=form.variant_label.data,
            size_value=form.size_value.data,
            size_unit=form.size_unit.data,
            base_uom=base_uom,
            purchase_uom=(form.purchase_uom.data or '').strip() or base_uom,
            units_per_purchase_uom=form.units_per_purchase_uom.data or 1,
            # No pack, no pack price. Leaving one behind is inert today, because
            # uom.price_for gates on has_conversion, but it is still a wrong
            # number in the row waiting for the pack to be re-added.
            pack_price=form.pack_price.data if form.has_pack() else None,
            # A unit nobody can be sold in is not a choice. If this product has
            # no real pack, "packs only" and "both" mean the same thing as
            # singles, and storing either would be a promise the sale form has
            # to break.
            sell_unit=_sell_unit_for(form),
        )
        # After construction, not inside it: deriving the per-single figures needs
        # the pack fields already on the product. Both columns are NOT NULL, so the
        # zeros above are placeholders that never reach a flush.
        _apply_prices(form, product, may_see_cost)
        db.session.add(product)
        db.session.commit()
        flash(f'Product added as {product.sku}. Stock is added by receiving a Purchase Order.', 'success')
        if not may_see_cost:
            flash('Cost price was left at 0 — ask an Owner or Manager to set it so margin '
                  'reporting is accurate.', 'warning')
        return redirect(url_for('products.list_products'))
    return render_template('products/add_edit.html', form=form, action='Add')

@products_bp.route('/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@permission_required('products.edit')
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    form = ProductForm(obj=product)
    may_see_cost = _strip_cost_price(form)
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    form.brand_id.choices = [(b.id, b.name) for b in Brand.query.filter_by(business_id=current_user.business_id).order_by(Brand.name)]
    form.item_group_id.choices = [(i.id, i.name) for i in ItemGroup.query.filter_by(business_id=current_user.business_id).order_by(ItemGroup.name)]
    
    if request.method == 'GET':
        form.quantity_in_stock.data = product.quantity_in_stock
        form.min_stock_alert.data = _min_stock_packs(product)
        # The stored cost is per single; the box asks for a pack. Multiplying back
        # returns exactly what was typed, which is the point of the widened column.
        if may_see_cost and uom.has_conversion(product):
            form.pack_cost.data = uom.cost_per_purchase_unit(product, product.cost_price)

    if form.validate_on_submit():
        brand, item_group, category = _scoped_catalogue(form)
        if not brand or not item_group:
            flash('Select a valid brand and item group.', 'danger')
            return render_template('products/add_edit.html', form=form, action='Edit')

        existing_sku, existing_qty = product.sku, product.quantity_in_stock
        existing_cost = product.cost_price
        existing_unit_price = product.unit_price
        existing_pack_price = product.pack_price
        form.populate_obj(product)

        # populate_obj skips the deleted field, but be explicit: a user who cannot
        # see cost price must never overwrite it, not even to null.
        if not may_see_cost:
            product.cost_price = existing_cost

        # Set the FK column, not the relationship. populate_obj has already written
        # category_id = 0 (the "No Category" sentinel), and assigning
        # product.category = None is a no-op when the relationship is already None -
        # so the 0 would survive and violate the foreign key.
        product.category_id = category.id if category else None
        product.brand_id = brand.id
        product.item_group_id = item_group.id

        # Blank optional fields must fall back rather than violate NOT NULL
        product.sku = (form.sku.data or '').strip() or existing_sku
        product.base_uom = (form.base_uom.data or '').strip() or 'pcs'
        product.purchase_uom = (form.purchase_uom.data or '').strip() or product.base_uom
        product.units_per_purchase_uom = form.units_per_purchase_uom.data or 1
        product.pack_price = form.pack_price.data if form.has_pack() else None
        product.sell_unit = _sell_unit_for(form)
        product.min_stock_alert = _min_stock_base(form)

        # populate_obj has just written whatever the hidden per-single boxes held,
        # which for a packed product is None against two NOT NULL columns. Derive
        # after it, never before.
        _apply_prices(form, product, may_see_cost)

        # Stock is owned by StockBatch/goods receipt, never by this form
        product.quantity_in_stock = existing_qty

        # "Who changed this price" is the question this log exists to answer, so
        # record the before and after rather than just that an edit happened.
        # The pack price goes first because it is the one somebody typed. Logging
        # only unit_price would have recorded a derived figure and missed the
        # decision behind it - and on a packed product the two always move together.
        if product.pack_price != existing_pack_price:
            audit.log('product.price_change', entity_type='product', entity_id=product.id,
                      sku=product.sku, field='pack_price',
                      old=str(existing_pack_price), new=str(product.pack_price))
        if product.unit_price != existing_unit_price:
            audit.log('product.price_change', entity_type='product', entity_id=product.id,
                      sku=product.sku, field='unit_price',
                      old=str(existing_unit_price), new=str(product.unit_price))
        if may_see_cost and product.cost_price != existing_cost:
            audit.log('product.price_change', entity_type='product', entity_id=product.id,
                      sku=product.sku, field='cost_price',
                      old=str(existing_cost), new=str(product.cost_price))

        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('products.list_products'))
    
    if product.category:
        form.category_id.data = product.category.id
    return render_template('products/add_edit.html', form=form, action='Edit')

@products_bp.route('/delete/<int:product_id>', methods=['POST'])
@login_required
@permission_required('products.delete')
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()

    blocker = _history_blocking_delete(product)
    if blocker:
        flash(f'{product.name} cannot be deleted because it has {blocker}. '
              'Deactivate it instead so it stops appearing in new sales and orders.', 'warning')
        return redirect(url_for('products.list_products'))

    audit.log('product.delete', entity_type='product', entity_id=product.id,
              sku=product.sku, name=product.name, stock_at_deletion=product.quantity_in_stock)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted!', 'info')
    return redirect(url_for('products.list_products'))


@products_bp.route('/deactivate/<int:product_id>', methods=['POST'])
@login_required
@permission_required('products.edit')
def toggle_product_active(product_id):
    """Retire a product without destroying its history.

    is_active has existed on the model since the variant restructure and nothing
    ever read or wrote it. This is what a wholesaler actually wants when they
    stop stocking something: it disappears from new sales and orders, while past
    sales, purchase orders and stock batches stay intact and reportable.
    """
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()

    if not product.is_active:
        # Switching one back on consumes the allowance exactly as creating one
        # does. Without this, a business over its cap could rotate through an
        # unlimited catalogue fifty products at a time.
        allowed, message = limits.can_add_product()
        if not allowed:
            flash(message, 'warning')
            return redirect(url_for('products.list_products'))

    product.is_active = not bool(product.is_active)
    audit.log('product.reactivate' if product.is_active else 'product.deactivate',
              entity_type='product', entity_id=product.id, sku=product.sku)
    db.session.commit()
    flash(f'{product.name} {"reactivated" if product.is_active else "deactivated"}.', 'success')
    return redirect(url_for('products.list_products'))

@products_bp.route('/upload', methods=['GET', 'POST'])
@login_required
@permission_required('products.create')
def upload_products():
    form = ProductUploadForm()
    if form.validate_on_submit():
        biz = current_user.business_id
        # Fall back to whatever catalogue rows exist. The previous lookup was for
        # 'Default Brand'/'Default ItemGroup', which nothing ever created, so this
        # route raised AttributeError on None for every upload.
        brand = (Brand.query.filter_by(business_id=biz, name='Generic').first()
                 or Brand.query.filter_by(business_id=biz).order_by(Brand.id).first())
        group = (ItemGroup.query.filter_by(business_id=biz, name='Uncategorized').first()
                 or ItemGroup.query.filter_by(business_id=biz).order_by(ItemGroup.id).first())
        if not brand or not group:
            flash('Add at least one brand and item group before uploading products.', 'warning')
            return redirect(url_for('products.list_products'))

        # A unique temporary path per upload, not the uploaded filename. Two
        # businesses uploading "products.xlsx" at the same moment would otherwise
        # share one path on disk - one overwriting, reading or deleting the
        # other's file, and importing another tenant's products.
        # (mkstemp also replaces the hardcoded /tmp, which does not exist on Windows.)
        # Checked before anything is written to disk. The cleanup that removes
        # filepath lives in a `finally` further down, so returning between
        # mkstemp and that try left an orphaned file behind on every rejected
        # upload from a business sitting at its cap.
        plan = limits.effective_plan(biz)
        remaining = None
        if plan is not None and plan.max_products is not None:
            remaining = max(0, plan.max_products - limits.active_product_count(biz))
            if remaining == 0:
                flash(limits.can_add_product(biz)[1], 'warning')
                return redirect(url_for('products.list_products'))

        suffix = os.path.splitext(secure_filename(form.file.data.filename))[1] or '.xlsx'
        descriptor, filepath = tempfile.mkstemp(prefix='product-upload-', suffix=suffix)
        os.close(descriptor)

        added, skipped, errors, over_limit = 0, 0, [], 0
        wb = None
        try:
            form.file.data.save(filepath)
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            ws = wb.active
            for line_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if row is None or all(c is None for c in row):
                    continue
                # Pad/trim rather than unpacking a fixed width, which raised
                # ValueError on any sheet that did not have exactly five columns.
                cells = (list(row) + [None] * 5)[:5]
                name, sku, description, unit_price, _qty = cells
                if not name:
                    errors.append(f'Row {line_no}: missing product name')
                    continue
                try:
                    price = Decimal(str(unit_price)) if unit_price is not None else Decimal('0')
                except (InvalidOperation, ValueError):
                    errors.append(f'Row {line_no}: "{unit_price}" is not a valid price')
                    continue

                sku = (str(sku).strip() if sku else '') or generate_sku(brand, group, str(name), biz)
                if Product.query.filter_by(sku=sku, business_id=biz).first():
                    skipped += 1
                    continue

                if remaining is not None and added >= remaining:
                    over_limit += 1
                    continue

                db.session.add(Product(
                    business_id=biz,
                    name=str(name).strip(),
                    sku=sku,
                    description=str(description).strip() if description else None,
                    # The sheet carries one price column, which is the sale price.
                    # Cost is genuinely unknown, so it starts at 0 for an Owner to
                    # fill in. Copying the sale price here would fabricate a zero
                    # margin and would also hand cost data to uploaders who are not
                    # allowed to see it (F-16).
                    cost_price=Decimal('0'),
                    unit_price=price,
                    quantity_in_stock=0,  # stock only ever enters via goods receipt
                    min_stock_alert=0,
                    brand_id=brand.id,
                    item_group_id=group.id,
                    base_uom='pcs',
                    purchase_uom='pcs',
                    units_per_purchase_uom=1
                ))
                added += 1
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('product upload failed')
            flash('That file could not be read. Check it is a valid Excel file.', 'danger')
            return render_template('products/upload.html', form=form)
        finally:
            # Close before deleting: if processing raised while the workbook was
            # open, Windows refuses to remove a file that still has a handle.
            if wb is not None:
                wb.close()
            if os.path.exists(filepath):
                os.remove(filepath)

        flash(f'{added} product(s) added, {skipped} skipped as duplicates.', 'success')
        if over_limit:
            flash(f'{over_limit} product(s) were not added because the {plan.name} plan covers '
                  f'{plan.max_products} active products. Upgrade to import the rest.', 'warning')
        if added:
            flash('Cost prices were left at 0 — set them so margin reporting is accurate.',
                  'warning')
        for msg in errors[:10]:
            flash(msg, 'warning')
        return redirect(url_for('products.list_products'))
    return render_template('products/upload.html', form=form)

@products_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('product_ids')
    if not ids:
        flash('No products selected.', 'warning')
        return redirect(url_for('products.list_products'))
    # Checked per action, not on the route: one endpoint, several privilege levels.
    required = {'delete': 'products.delete',
                'export_csv': 'reports.export',
                'export_excel': 'reports.export'}.get(action)
    if not required or not current_user.can(required):
        flash('You do not have permission to do that.', 'danger')
        return redirect(url_for('products.list_products'))

    products = Product.query.filter(Product.id.in_(ids), Product.business_id == current_user.business_id).all()
    if action == 'delete':
        # Same rule as the single delete: anything that has traded is kept.
        deletable = [p for p in products if not _history_blocking_delete(p)]
        blocked = [p for p in products if p not in deletable]

        if deletable:
            audit.log('product.bulk_delete', entity_type='product',
                      count=len(deletable), skus=[p.sku for p in deletable])
            for product in deletable:
                db.session.delete(product)
            db.session.commit()
            flash(f'{len(deletable)} product(s) deleted.', 'success')
        if blocked:
            flash(f'{len(blocked)} product(s) kept because they have sales, orders or stock '
                  f'history: {", ".join(p.name for p in blocked[:5])}'
                  f'{"..." if len(blocked) > 5 else ""}. Deactivate them instead.', 'warning')
        return redirect(url_for('products.list_products'))
    elif action in ('export_csv', 'export_excel'):
        # The export is the easiest way to walk out with margins, so it obeys the
        # same gate as the screen - the column is omitted entirely, not blanked.
        show_cost = current_user.can('products.cost_price.view')
        headers = ['Name', 'SKU', 'Brand', 'Item Group', 'Variant']
        if show_cost:
            headers.append('Cost Price')
        headers += ['Unit Price', 'Quantity in Stock']

        data = []
        for p in products:
            row = [
                p.name,
                p.sku,
                p.brand.name if p.brand else '',
                p.item_group.name if p.item_group else '',
                p.variant_label,
            ]
            if show_cost:
                # Stored to six decimals because it is derived from a pack cost;
                # nobody wants to read 41.666667 in a spreadsheet. Rounded here
                # rather than stored short, so the round trip stays exact.
                row.append(round(float(p.cost_price or 0), 2))
            row += [float(p.unit_price or 0), p.quantity_in_stock]
            data.append(row)
        df = pd.DataFrame(data, columns=headers)

        if action == 'export_excel':
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Products')
            output.seek(0)
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name='products_bulk_export.xlsx'
            )

        output = io.StringIO()
        df.to_csv(output, index=False)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='products_bulk_export.csv'
        )
    else:
        flash('Invalid bulk action.', 'danger')
        return redirect(url_for('products.list_products'))

# Category management
@products_bp.route('/categories')
@login_required
@permission_required('catalogue.manage')
def list_categories():
    categories = Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
    return render_template('products/categories.html', categories=categories)

@products_bp.route('/categories/add', methods=['GET', 'POST'])
@login_required
@permission_required('catalogue.manage')
def add_category():
    form = CategoryForm()
    if form.validate_on_submit():
        category = Category(business_id=current_user.business_id, name=form.name.data, description=form.description.data)
        db.session.add(category)
        db.session.commit()
        flash('Category added!', 'success')
        return redirect(url_for('products.list_categories'))
    return render_template('products/category_form.html', form=form, action='Add')

@products_bp.route('/categories/edit/<int:category_id>', methods=['GET', 'POST'])
@login_required
@permission_required('catalogue.manage')
def edit_category(category_id):
    category = Category.query.filter_by(id=category_id, business_id=current_user.business_id).first_or_404()
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        form.populate_obj(category)
        db.session.commit()
        flash('Category updated!', 'success')
        return redirect(url_for('products.list_categories'))
    return render_template('products/category_form.html', form=form, action='Edit')

@products_bp.route('/categories/delete/<int:category_id>', methods=['POST'])
@login_required
@permission_required('catalogue.manage')
def delete_category(category_id):
    category = Category.query.filter_by(id=category_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted!', 'info')
    return redirect(url_for('products.list_categories'))

# Brand management
@products_bp.route('/brands')
@login_required
@permission_required('catalogue.manage')
def list_brands():
    brands = Brand.query.filter_by(business_id=current_user.business_id).order_by(Brand.name).all()
    return render_template('products/brands.html', brands=brands)

@products_bp.route('/brands/add', methods=['GET', 'POST'])
@login_required
@permission_required('catalogue.manage')
def add_brand():
    form = BrandForm()
    if form.validate_on_submit():
        brand = Brand(business_id=current_user.business_id, name=form.name.data)
        db.session.add(brand)
        db.session.commit()
        flash('Brand added!', 'success')
        return redirect(url_for('products.list_brands'))
    return render_template('products/brand_form.html', form=form, action='Add')

@products_bp.route('/brands/edit/<int:brand_id>', methods=['GET', 'POST'])
@login_required
@permission_required('catalogue.manage')
def edit_brand(brand_id):
    brand = Brand.query.filter_by(id=brand_id, business_id=current_user.business_id).first_or_404()
    form = BrandForm(obj=brand)
    if form.validate_on_submit():
        form.populate_obj(brand)
        db.session.commit()
        flash('Brand updated!', 'success')
        return redirect(url_for('products.list_brands'))
    return render_template('products/brand_form.html', form=form, action='Edit')

@products_bp.route('/brands/delete/<int:brand_id>', methods=['POST'])
@login_required
@permission_required('catalogue.manage')
def delete_brand(brand_id):
    brand = Brand.query.filter_by(id=brand_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(brand)
    db.session.commit()
    flash('Brand deleted!', 'info')
    return redirect(url_for('products.list_brands'))

# Item Group management
@products_bp.route('/item_groups')
@login_required
@permission_required('catalogue.manage')
def list_item_groups():
    item_groups = ItemGroup.query.filter_by(business_id=current_user.business_id).order_by(ItemGroup.name).all()
    return render_template('products/item_groups.html', item_groups=item_groups)

@products_bp.route('/item_groups/add', methods=['GET', 'POST'])
@login_required
@permission_required('catalogue.manage')
def add_item_group():
    form = ItemGroupForm()
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    if form.validate_on_submit():
        category_id = form.category_id.data if form.category_id.data and form.category_id.data != 0 else None
        item_group = ItemGroup(business_id=current_user.business_id, name=form.name.data,
                               category_id=category_id,
                               track_expiry=bool(form.track_expiry.data))
        db.session.add(item_group)
        db.session.commit()
        flash('Item Group added!', 'success')
        return redirect(url_for('products.list_item_groups'))
    return render_template('products/item_group_form.html', form=form, action='Add')

@products_bp.route('/item_groups/edit/<int:item_group_id>', methods=['GET', 'POST'])
@login_required
@permission_required('catalogue.manage')
def edit_item_group(item_group_id):
    item_group = ItemGroup.query.filter_by(id=item_group_id, business_id=current_user.business_id).first_or_404()
    form = ItemGroupForm(obj=item_group)
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    if form.validate_on_submit():
        item_group.name = form.name.data
        item_group.category_id = form.category_id.data if form.category_id.data and form.category_id.data != 0 else None
        item_group.track_expiry = bool(form.track_expiry.data)
        db.session.commit()
        flash('Item Group updated!', 'success')
        return redirect(url_for('products.list_item_groups'))
    if item_group.category_id:
        form.category_id.data = item_group.category_id
    return render_template('products/item_group_form.html', form=form, action='Edit')

@products_bp.route('/item_groups/delete/<int:item_group_id>', methods=['POST'])
@login_required
@permission_required('catalogue.manage')
def delete_item_group(item_group_id):
    item_group = ItemGroup.query.filter_by(id=item_group_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(item_group)
    db.session.commit()
    flash('Item Group deleted!', 'info')
    return redirect(url_for('products.list_item_groups'))

# Supplier management
@products_bp.route('/suppliers')
@login_required
@permission_required('suppliers.view')
def list_suppliers():
    term = listing.search_term()
    sort = listing.sort_key(SUPPLIER_SORTS, 'name')
    query = listing.apply_search(
        Supplier.query.filter_by(business_id=current_user.business_id), term,
        [Supplier.name, Supplier.contact, Supplier.phone, Supplier.email])
    suppliers = listing.apply_sort(query, SUPPLIER_SORTS, sort).all()
    return render_template('products/suppliers.html', suppliers=suppliers,
                           q=term, sort=sort, sort_options=SUPPLIER_SORT_LABELS,
                           is_filtered=listing.is_filtered('q'))

@products_bp.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
@permission_required('suppliers.manage')
def add_supplier():
    form = SupplierForm()
    if form.validate_on_submit():
        supplier = Supplier(
            business_id=current_user.business_id,
            name=form.name.data,
            contact=form.contact.data,
            phone=form.phone.data,
            email=form.email.data,
            address=form.address.data
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier added!', 'success')
        return redirect(url_for('products.list_suppliers'))
    return render_template('products/supplier_form.html', form=form, action='Add')

@products_bp.route('/suppliers/edit/<int:supplier_id>', methods=['GET', 'POST'])
@login_required
@permission_required('suppliers.manage')
def edit_supplier(supplier_id):
    supplier = Supplier.query.filter_by(id=supplier_id, business_id=current_user.business_id).first_or_404()
    form = SupplierForm(obj=supplier)
    if form.validate_on_submit():
        form.populate_obj(supplier)
        db.session.commit()
        flash('Supplier updated!', 'success')
        return redirect(url_for('products.list_suppliers'))
    return render_template('products/supplier_form.html', form=form, action='Edit')

@products_bp.route('/suppliers/delete/<int:supplier_id>', methods=['POST'])
@login_required
@permission_required('suppliers.manage')
def delete_supplier(supplier_id):
    supplier = Supplier.query.filter_by(id=supplier_id, business_id=current_user.business_id).first_or_404()

    # PurchaseOrder.supplier_id is nullable with no cascade, so deleting a
    # supplier silently nulls its orders - and the price-comparison history
    # requires a supplier, so those orders vanish from it. Same rule as
    # products: history is never destroyed to tidy a list.
    orders = PurchaseOrder.query.filter_by(supplier_id=supplier.id).count()
    if orders:
        flash(f'{supplier.name} cannot be deleted: {orders} purchase '
              f'{"order" if orders == 1 else "orders"} reference them. '
              'Their price history would be lost.', 'warning')
        return redirect(url_for('products.list_suppliers'))

    audit.log('supplier.delete', entity_type='supplier', entity_id=supplier.id, name=supplier.name)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted!', 'info')
    return redirect(url_for('products.list_suppliers'))