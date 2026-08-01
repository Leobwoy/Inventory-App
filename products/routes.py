from flask import render_template, redirect, url_for, flash, request
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

@products_bp.route('/')
@login_required
def list_products():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    
    query = Product.query.filter_by(business_id=current_user.business_id)
    if search_query:
        query = query.filter(db.or_(
            Product.name.ilike(f'%{search_query}%'),
            Product.sku.ilike(f'%{search_query}%'),
            Product.barcode.ilike(f'%{search_query}%'),
            Product.variant_label.ilike(f'%{search_query}%')
        ))
        
    pagination = query.order_by(Product.name).paginate(page=page, per_page=15, error_out=False)
    return render_template('products/list.html', products=pagination.items, pagination=pagination, search_query=search_query)

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


@products_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_product():
    form = ProductForm()
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    form.brand_id.choices = [(b.id, b.name) for b in Brand.query.filter_by(business_id=current_user.business_id).order_by(Brand.name)]
    form.item_group_id.choices = [(i.id, i.name) for i in ItemGroup.query.filter_by(business_id=current_user.business_id).order_by(ItemGroup.name)]

    # Do not allow modifying quantity during creation; handled via PO/StockBatch
    if request.method == 'GET':
        form.quantity_in_stock.data = 0

    if form.validate_on_submit():
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
            cost_price=form.cost_price.data,
            unit_price=form.unit_price.data,
            quantity_in_stock=0, # Initialized to 0, managed via StockBatch
            min_stock_alert=form.min_stock_alert.data or 0,
            category=category,
            brand_id=brand.id,
            item_group_id=item_group.id,
            variant_label=form.variant_label.data,
            size_value=form.size_value.data,
            size_unit=form.size_unit.data,
            base_uom=base_uom,
            purchase_uom=(form.purchase_uom.data or '').strip() or base_uom,
            units_per_purchase_uom=form.units_per_purchase_uom.data or 1
        )
        db.session.add(product)
        db.session.commit()
        flash(f'Product added as {product.sku}. Stock is added by receiving a Purchase Order.', 'success')
        return redirect(url_for('products.list_products'))
    return render_template('products/add_edit.html', form=form, action='Add')

@products_bp.route('/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    form = ProductForm(obj=product)
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    form.brand_id.choices = [(b.id, b.name) for b in Brand.query.filter_by(business_id=current_user.business_id).order_by(Brand.name)]
    form.item_group_id.choices = [(i.id, i.name) for i in ItemGroup.query.filter_by(business_id=current_user.business_id).order_by(ItemGroup.name)]
    
    if request.method == 'GET':
        form.quantity_in_stock.data = product.quantity_in_stock

    if form.validate_on_submit():
        brand, item_group, category = _scoped_catalogue(form)
        if not brand or not item_group:
            flash('Select a valid brand and item group.', 'danger')
            return render_template('products/add_edit.html', form=form, action='Edit')

        existing_sku, existing_qty = product.sku, product.quantity_in_stock
        form.populate_obj(product)

        product.category = category
        product.brand_id = brand.id
        product.item_group_id = item_group.id

        # Blank optional fields must fall back rather than violate NOT NULL
        product.sku = (form.sku.data or '').strip() or existing_sku
        product.base_uom = (form.base_uom.data or '').strip() or 'pcs'
        product.purchase_uom = (form.purchase_uom.data or '').strip() or product.base_uom
        product.units_per_purchase_uom = form.units_per_purchase_uom.data or 1
        product.min_stock_alert = form.min_stock_alert.data or 0

        # Stock is owned by StockBatch/goods receipt, never by this form
        product.quantity_in_stock = existing_qty

        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('products.list_products'))
    
    if product.category:
        form.category_id.data = product.category.id
    return render_template('products/add_edit.html', form=form, action='Edit')

@products_bp.route('/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted!', 'info')
    return redirect(url_for('products.list_products'))

@products_bp.route('/upload', methods=['GET', 'POST'])
@login_required
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

        # tempfile, not a hardcoded /tmp, which does not exist on Windows (F-20)
        filename = secure_filename(form.file.data.filename)
        filepath = os.path.join(tempfile.gettempdir(), filename)
        added, skipped, errors = 0, 0, []
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

                db.session.add(Product(
                    business_id=biz,
                    name=str(name).strip(),
                    sku=sku,
                    description=str(description).strip() if description else None,
                    cost_price=price,
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
            wb.close()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Upload failed: {e}', 'danger')
            return render_template('products/upload.html', form=form)
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

        flash(f'{added} product(s) added, {skipped} skipped as duplicates.', 'success')
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
    products = Product.query.filter(Product.id.in_(ids), Product.business_id == current_user.business_id).all()
    if action == 'delete':
        for product in products:
            db.session.delete(product)
        db.session.commit()
        flash(f'{len(products)} products deleted.', 'success')
        return redirect(url_for('products.list_products'))
    elif action in ('export_csv', 'export_excel'):
        headers = ['Name', 'SKU', 'Brand', 'Item Group', 'Variant', 'Cost Price', 'Unit Price', 'Quantity in Stock']
        data = [[
            p.name,
            p.sku,
            p.brand.name if p.brand else '',
            p.item_group.name if p.item_group else '',
            p.variant_label,
            float(p.cost_price or 0),
            float(p.unit_price or 0),
            p.quantity_in_stock,
        ] for p in products]
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
def list_categories():
    categories = Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
    return render_template('products/categories.html', categories=categories)

@products_bp.route('/categories/add', methods=['GET', 'POST'])
@login_required
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
def delete_category(category_id):
    category = Category.query.filter_by(id=category_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted!', 'info')
    return redirect(url_for('products.list_categories'))

# Brand management
@products_bp.route('/brands')
@login_required
def list_brands():
    brands = Brand.query.filter_by(business_id=current_user.business_id).order_by(Brand.name).all()
    return render_template('products/brands.html', brands=brands)

@products_bp.route('/brands/add', methods=['GET', 'POST'])
@login_required
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
def delete_brand(brand_id):
    brand = Brand.query.filter_by(id=brand_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(brand)
    db.session.commit()
    flash('Brand deleted!', 'info')
    return redirect(url_for('products.list_brands'))

# Item Group management
@products_bp.route('/item_groups')
@login_required
def list_item_groups():
    item_groups = ItemGroup.query.filter_by(business_id=current_user.business_id).order_by(ItemGroup.name).all()
    return render_template('products/item_groups.html', item_groups=item_groups)

@products_bp.route('/item_groups/add', methods=['GET', 'POST'])
@login_required
def add_item_group():
    form = ItemGroupForm()
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    if form.validate_on_submit():
        category_id = form.category_id.data if form.category_id.data and form.category_id.data != 0 else None
        item_group = ItemGroup(business_id=current_user.business_id, name=form.name.data, category_id=category_id)
        db.session.add(item_group)
        db.session.commit()
        flash('Item Group added!', 'success')
        return redirect(url_for('products.list_item_groups'))
    return render_template('products/item_group_form.html', form=form, action='Add')

@products_bp.route('/item_groups/edit/<int:item_group_id>', methods=['GET', 'POST'])
@login_required
def edit_item_group(item_group_id):
    item_group = ItemGroup.query.filter_by(id=item_group_id, business_id=current_user.business_id).first_or_404()
    form = ItemGroupForm(obj=item_group)
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name)]
    if form.validate_on_submit():
        item_group.name = form.name.data
        item_group.category_id = form.category_id.data if form.category_id.data and form.category_id.data != 0 else None
        db.session.commit()
        flash('Item Group updated!', 'success')
        return redirect(url_for('products.list_item_groups'))
    if item_group.category_id:
        form.category_id.data = item_group.category_id
    return render_template('products/item_group_form.html', form=form, action='Edit')

@products_bp.route('/item_groups/delete/<int:item_group_id>', methods=['POST'])
@login_required
def delete_item_group(item_group_id):
    item_group = ItemGroup.query.filter_by(id=item_group_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(item_group)
    db.session.commit()
    flash('Item Group deleted!', 'info')
    return redirect(url_for('products.list_item_groups'))

# Supplier management
@products_bp.route('/suppliers')
@login_required
def list_suppliers():
    suppliers = Supplier.query.filter_by(business_id=current_user.business_id).order_by(Supplier.name).all()
    return render_template('products/suppliers.html', suppliers=suppliers)

@products_bp.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
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
def delete_supplier(supplier_id):
    supplier = Supplier.query.filter_by(id=supplier_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted!', 'info')
    return redirect(url_for('products.list_suppliers'))