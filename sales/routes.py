from flask import render_template, redirect, url_for, flash, request, current_app
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
from flask_login import login_required, current_user
from auth.decorators import permission_required
from services import audit, pricing, stock

@sales_bp.route('/')
@login_required
@permission_required('sales.view')
def list_sales():
    page = request.args.get('page', 1, type=int)
    pagination = Sale.query.filter_by(business_id=current_user.business_id).order_by(Sale.sale_date.desc()).paginate(page=page, per_page=15, error_out=False)
    return render_template('sales/list.html', sales=pagination.items, pagination=pagination)

@sales_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('sales.create')
def add_sale():
    form = SaleForm()
    product_choices = [(str(p.id), p.name) for p in Product.query.filter_by(business_id=current_user.business_id).all()]
    product_prices = {str(p.id): float(p.unit_price) for p in Product.query.filter_by(business_id=current_user.business_id).all()}
    for item_form in form.items:
        item_form.form.product_id.choices = product_choices  # type: ignore
    form.customer_id.choices = [('0', 'No Customer')] + [(str(c.id), c.name) for c in Customer.query.filter_by(business_id=current_user.business_id).order_by(Customer.name)]  # type: ignore
    if form.validate_on_submit():
        customer_id = int(form.customer_id.data) if form.customer_id.data and form.customer_id.data != '0' else None
        customer_name = form.customer_name.data.strip() if form.customer_name.data else None
        try:
            sale = Sale()
            sale.business_id = current_user.business_id
            sale.sale_date = form.sale_date.data or date.today()
            sale.customer_id = customer_id
            db.session.add(sale)
            deviations = []
            # Save all sale items
            for item_form in form.items:
                product = Product.query.filter_by(id=int(item_form.product_id.data), business_id=current_user.business_id).first()
                if not product:
                    db.session.rollback()
                    flash('One of the selected products is not available.', 'danger')
                    return render_template('sales/add.html', form=form, product_prices=product_prices,
                               can_discount=current_user.can('sales.discount'),
                               max_discount=current_user.business.max_discount_percent)

                # The server decides the price. A posted value is only a request:
                # readonly in the template never stopped an edited POST (F-07).
                charged, deviation = pricing.resolve(
                    product=product,
                    business=current_user.business,
                    requested_price=item_form.price_at_sale.data,
                    may_discount=current_user.can('sales.discount'),
                )

                sale_item = SaleItem()
                sale_item.product_id = product.id
                sale_item.quantity = item_form.quantity.data
                sale_item.price_at_sale = charged
                sale.items.append(sale_item)
                deviations.append((product, deviation))

                # Stock moves only through the service, which draws down FEFO and
                # refreshes the cached quantity from the batch sum (F-12).
                stock.deduct_fefo(product, item_form.quantity.data, current_user.business_id)

            db.session.flush()   # sale.id, needed by the audit entries
            for product, deviation in deviations:
                pricing.record_deviation(sale, product, deviation)

            db.session.commit()
            flash('Sale recorded!', 'success')
            return redirect(url_for('sales.sale_invoice', sale_id=sale.id, customer_name=customer_name))
        except pricing.PriceRejected as e:
            db.session.rollback()
            flash(str(e), 'danger')
            return render_template('sales/add.html', form=form, product_prices=product_prices,
                               can_discount=current_user.can('sales.discount'),
                               max_discount=current_user.business.max_discount_percent)
        except stock.InsufficientStock as e:
            db.session.rollback()
            flash(str(e), 'danger')
            return render_template('sales/add.html', form=form, product_prices=product_prices,
                               can_discount=current_user.can('sales.discount'),
                               max_discount=current_user.business.max_discount_percent)
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('%s failed', request.endpoint)
            flash('Something went wrong and nothing was saved. Please try again.', 'danger')
            return render_template('sales/add.html', form=form, product_prices=product_prices,
                               can_discount=current_user.can('sales.discount'),
                               max_discount=current_user.business.max_discount_percent)
    return render_template('sales/add.html', form=form, product_prices=product_prices,
                               can_discount=current_user.can('sales.discount'),
                               max_discount=current_user.business.max_discount_percent)

# Customer management
@sales_bp.route('/customers')
@login_required
@permission_required('customers.view')
def list_customers():
    customers = Customer.query.filter_by(business_id=current_user.business_id).order_by(Customer.name).all()
    return render_template('sales/customers.html', customers=customers)

@sales_bp.route('/customers/add', methods=['GET', 'POST'])
@login_required
@permission_required('customers.manage')
def add_customer():
    form = CustomerForm()
    if form.validate_on_submit():
        customer = Customer()
        customer.business_id = current_user.business_id
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
@login_required
@permission_required('customers.manage')
def edit_customer(customer_id):
    customer = Customer.query.filter_by(id=customer_id, business_id=current_user.business_id).first_or_404()
    form = CustomerForm(obj=customer)
    if form.validate_on_submit():
        form.populate_obj(customer)
        db.session.commit()
        flash('Customer updated!', 'success')
        return redirect(url_for('sales.list_customers'))
    return render_template('sales/customer_form.html', form=form, action='Edit')

@sales_bp.route('/customers/delete/<int:customer_id>', methods=['POST'])
@login_required
@permission_required('customers.manage')
def delete_customer(customer_id):
    customer = Customer.query.filter_by(id=customer_id, business_id=current_user.business_id).first_or_404()
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted!', 'info')
    return redirect(url_for('sales.list_customers'))

@sales_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('sale_ids')
    if not ids:
        flash('No sales selected.', 'warning')
        return redirect(url_for('sales.list_sales'))
    # Checked per action, not on the route: one endpoint, several privilege levels.
    required = {'delete': 'sales.void',
                'export_csv': 'reports.export',
                'export_excel': 'reports.export',
                'print_invoices': 'sales.view'}.get(action)
    if not required or not current_user.can(required):
        flash('You do not have permission to do that.', 'danger')
        return redirect(url_for('sales.list_sales'))

    sales = Sale.query.filter(Sale.id.in_(ids), Sale.business_id == current_user.business_id).all()
    if action == 'delete':
        try:
            for sale in sales:
                for item in sale.items:
                    if item.product:
                        # Restores into the batches the stock came from. Previously
                        # this incremented only Product.quantity_in_stock, so the
                        # cache and the batch sum diverged permanently (F-12).
                        stock.restore(item.product, item.quantity, current_user.business_id)
                db.session.delete(sale)
            db.session.commit()
            flash(f'{len(sales)} sales deleted and stock restored.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('%s bulk delete failed', request.endpoint)
            flash('Something went wrong and nothing was deleted.', 'danger')
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
@login_required
@permission_required('sales.view')
def sale_invoice(sale_id):
    sale = Sale.query.filter_by(id=sale_id, business_id=current_user.business_id).first_or_404()
    customer_name = request.args.get('customer_name')
    return render_template('sales/invoice.html', sale=sale, customer_name=customer_name)

@sales_bp.route('/bulk_print_invoices')
@login_required
@permission_required('sales.view')
def bulk_print_invoices():
    ids = request.args.get('ids', '')
    id_list = [int(i) for i in ids.split(',') if i.isdigit()]
    sales = Sale.query.filter(Sale.id.in_(id_list), Sale.business_id == current_user.business_id).all()
    return render_template('sales/bulk_invoices.html', sales=sales)