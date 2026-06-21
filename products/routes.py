from flask import render_template, redirect, url_for, flash, request
from . import products_bp
from .models import Product, Category, Supplier
from .forms import ProductForm, ProductUploadForm, CategoryForm, SupplierForm
from extensions import db
from werkzeug.utils import secure_filename
import openpyxl
import os
import pandas as pd
from flask import send_file
import io

@products_bp.route('/')
def list_products():
    products = Product.query.all()
    return render_template('products/list.html', products=products)

@products_bp.route('/add', methods=['GET', 'POST'])
def add_product():
    form = ProductForm()
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.order_by(Category.name)]
    if form.validate_on_submit():
        category = Category.query.get(form.category_id.data) if form.category_id.data else None
        product = Product(
            name=form.name.data,
            sku=form.sku.data,
            description=form.description.data,
            unit_price=form.unit_price.data,
            quantity_in_stock=form.quantity_in_stock.data,
            min_stock_alert=form.min_stock_alert.data,
            category=category
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully!', 'success')
        return redirect(url_for('products.list_products'))
    return render_template('products/add_edit.html', form=form, action='Add')

@products_bp.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product)
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.order_by(Category.name)]
    if form.validate_on_submit():
        form.populate_obj(product)
        product.category = Category.query.get(form.category_id.data) if form.category_id.data else None
        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('products.list_products'))
    if product.category:
        form.category_id.data = product.category.id
    return render_template('products/add_edit.html', form=form, action='Edit')

@products_bp.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted!', 'info')
    return redirect(url_for('products.list_products'))

@products_bp.route('/upload', methods=['GET', 'POST'])
def upload_products():
    form = ProductUploadForm()
    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename)
        filepath = os.path.join('/tmp', filename)
        file.save(filepath)
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        for row in ws.iter_rows(min_row=2, values_only=True):
            name, sku, description, unit_price, quantity_in_stock = row
            if not Product.query.filter_by(sku=sku).first():
                product = Product(
                    name=name,
                    sku=sku,
                    description=description,
                    unit_price=unit_price,
                    quantity_in_stock=quantity_in_stock
                )
                db.session.add(product)
        db.session.commit()
        flash('Products uploaded successfully!', 'success')
        return redirect(url_for('products.list_products'))
    return render_template('products/upload.html', form=form)

@products_bp.route('/bulk_action', methods=['POST'])
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('product_ids')
    if not ids:
        flash('No products selected.', 'warning')
        return redirect(url_for('products.list_products'))
    products = Product.query.filter(Product.id.in_(ids)).all()
    if action == 'delete':
        for product in products:
            db.session.delete(product)
        db.session.commit()
        flash(f'{len(products)} products deleted.', 'success')
        return redirect(url_for('products.list_products'))
    elif action == 'export_csv':
        headers = ['Name', 'SKU', 'Description', 'Unit Price', 'Quantity in Stock', 'Min Stock Alert']
        data = [[p.name, p.sku, p.description, float(p.unit_price), p.quantity_in_stock, p.min_stock_alert] for p in products]
        df = pd.DataFrame(data, columns=headers)
        output = pd.io.common.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='products_bulk_export.csv'
        )
    elif action == 'export_excel':
        headers = ['Name', 'SKU', 'Description', 'Unit Price', 'Quantity in Stock', 'Min Stock Alert']
        data = [[p.name, p.sku, p.description, float(p.unit_price), p.quantity_in_stock, p.min_stock_alert] for p in products]
        df = pd.DataFrame(data, columns=headers)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='products_bulk_export.xlsx'
        )
    else:
        flash('Invalid bulk action.', 'danger')
        return redirect(url_for('products.list_products'))

# Category management
@products_bp.route('/categories')
def list_categories():
    categories = Category.query.order_by(Category.name).all()
    return render_template('products/categories.html', categories=categories)

@products_bp.route('/categories/add', methods=['GET', 'POST'])
def add_category():
    form = CategoryForm()
    if form.validate_on_submit():
        category = Category(name=form.name.data, description=form.description.data)
        db.session.add(category)
        db.session.commit()
        flash('Category added!', 'success')
        return redirect(url_for('products.list_categories'))
    return render_template('products/category_form.html', form=form, action='Add')

@products_bp.route('/categories/edit/<int:category_id>', methods=['GET', 'POST'])
def edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        form.populate_obj(category)
        db.session.commit()
        flash('Category updated!', 'success')
        return redirect(url_for('products.list_categories'))
    return render_template('products/category_form.html', form=form, action='Edit')

@products_bp.route('/categories/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted!', 'info')
    return redirect(url_for('products.list_categories'))

# Supplier management
@products_bp.route('/suppliers')
def list_suppliers():
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('products/suppliers.html', suppliers=suppliers)

@products_bp.route('/suppliers/add', methods=['GET', 'POST'])
def add_supplier():
    form = SupplierForm()
    if form.validate_on_submit():
        supplier = Supplier(
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
def edit_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    form = SupplierForm(obj=supplier)
    if form.validate_on_submit():
        form.populate_obj(supplier)
        db.session.commit()
        flash('Supplier updated!', 'success')
        return redirect(url_for('products.list_suppliers'))
    return render_template('products/supplier_form.html', form=form, action='Edit')

@products_bp.route('/suppliers/delete/<int:supplier_id>', methods=['POST'])
def delete_supplier(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted!', 'info')
    return redirect(url_for('products.list_suppliers')) 