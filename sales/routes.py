from flask import render_template, redirect, url_for, flash, request
from . import sales_bp
from .models import Sale, Customer
from products.models import Product
from .forms import SaleForm, CustomerForm
from extensions import db
from datetime import date
import pandas as pd
from flask import send_file
import io
from .models import SaleItem

@sales_bp.route('/')
def list_sales():
    sales = Sale.query.order_by(Sale.sale_date.desc()).all()
    return render_template('sales/list.html', sales=sales)

@sales_bp.route('/add', methods=['GET', 'POST'])
def add_sale():
    form = SaleForm()
    product_choices = [(str(p.id), p.name) for p in Product.query.all()]
    product_prices = {str(p.id): float(p.unit_price) for p in Product.query.all()}
    for item_form in form.items:
        item_form.form.product_id.choices = product_choices  # type: ignore
    form.customer_id.choices = [('0', 'No Customer')] + [(str(c.id), c.name) for c in Customer.query.order_by(Customer.name)]  # type: ignore
    if form.validate_on_submit():
        customer_id = int(form.customer_id.data) if form.customer_id.data and form.customer_id.data != '0' else None
        customer_name = form.customer_name.data.strip() if form.customer_name.data else None
        sale = Sale()
        sale.sale_date = form.sale_date.data or date.today()
        sale.customer_id = customer_id
        db.session.add(sale)
        # Save all sale items
        for item_form in form.items:
            product = Product.query.get(int(item_form.product_id.data))
            if product and product.quantity_in_stock >= item_form.quantity.data:
                sale_item = SaleItem()
                sale_item.product_id = product.id
                sale_item.quantity = item_form.quantity.data
                sale_item.price_at_sale = item_form.price_at_sale.data
                sale.items.append(sale_item)
                product.quantity_in_stock -= item_form.quantity.data
            else:
                flash(f'Not enough stock for {product.name if product else "Unknown Product"}.', 'danger')
                return render_template('sales/add.html', form=form)
        db.session.commit()
        flash('Sale recorded!', 'success')
        return redirect(url_for('sales.sale_invoice', sale_id=sale.id, customer_name=customer_name))
    return render_template('sales/add.html', form=form, product_prices=product_prices)

# Customer management
@sales_bp.route('/customers')
def list_customers():
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('sales/customers.html', customers=customers)

@sales_bp.route('/customers/add', methods=['GET', 'POST'])
def add_customer():
    form = CustomerForm()
    if form.validate_on_submit():
        customer = Customer()
        customer.name = form.name.data
        customer.phone = form.phone.data
        customer.email = form.email.data
        customer.address = form.address.data
        db.session.add(customer)
        db.session.commit()
        flash('Customer added!', 'success')
        return redirect(url_for('sales.list_customers'))
    return render_template('sales/customer_form.html', form=form, action='Add')

@sales_bp.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST'])
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerForm(obj=customer)
    if form.validate_on_submit():
        form.populate_obj(customer)
        db.session.commit()
        flash('Customer updated!', 'success')
        return redirect(url_for('sales.list_customers'))
    return render_template('sales/customer_form.html', form=form, action='Edit')

@sales_bp.route('/customers/delete/<int:customer_id>', methods=['POST'])
def delete_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted!', 'info')
    return redirect(url_for('sales.list_customers'))

@sales_bp.route('/bulk_action', methods=['POST'])
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('sale_ids')
    if not ids:
        flash('No sales selected.', 'warning')
        return redirect(url_for('sales.list_sales'))
    sales = Sale.query.filter(Sale.id.in_(ids)).all()
    if action == 'delete':
        for sale in sales:
            db.session.delete(sale)
        db.session.commit()
        flash(f'{len(sales)} sales deleted.', 'success')
        return redirect(url_for('sales.list_sales'))
    elif action == 'export_csv':
        headers = ['Date', 'Product', 'Quantity', 'Unit Price', 'Total']
        data = []
        for s in sales:
            for item in s.items:
                data.append([s.sale_date, item.product.name, item.quantity, float(item.price_at_sale), float(item.price_at_sale * item.quantity)])
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(data)
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='sales_bulk_export.csv'
        )
    elif action == 'export_excel':
        headers = ['Date', 'Product', 'Quantity', 'Unit Price', 'Total']
        data = []
        for s in sales:
            for item in s.items:
                data.append([s.sale_date, item.product.name, item.quantity, float(item.price_at_sale), float(item.price_at_sale * item.quantity)])
        import xlsxwriter
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet()
        for col, header in enumerate(headers):
            worksheet.write(0, col, header)
        for row_idx, row in enumerate(data, 1):
            for col_idx, value in enumerate(row):
                worksheet.write(row_idx, col_idx, value)
        workbook.close()
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='sales_bulk_export.xlsx'
        )
    elif action == 'print_invoices':
        return redirect(url_for('sales.bulk_print_invoices', ids=','.join(ids)))
    else:
        flash('Invalid bulk action.', 'danger')
        return redirect(url_for('sales.list_sales'))

@sales_bp.route('/invoice/<int:sale_id>')
def sale_invoice(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    customer_name = request.args.get('customer_name')
    return render_template('sales/invoice.html', sale=sale, customer_name=customer_name)

@sales_bp.route('/bulk_print_invoices')
def bulk_print_invoices():
    ids = request.args.get('ids', '')
    id_list = [int(i) for i in ids.split(',') if i.isdigit()]
    sales = Sale.query.filter(Sale.id.in_(id_list)).all()
    return render_template('sales/bulk_invoices.html', sales=sales) 