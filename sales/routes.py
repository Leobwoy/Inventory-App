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
from auth.decorators import permission_required, requires_feature
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from decimal import Decimal
from services import audit, credit as credit_service, limits, listing, pricing, stock, uom

# Sorting by value needs the totals subquery, so it is applied in the view
# rather than here; it still has to be in the whitelist to be accepted.
SALE_SORTS = {
    'newest':  [Sale.sale_date.desc(), Sale.id.desc()],
    'oldest':  [Sale.sale_date.asc(), Sale.id.asc()],
    'largest': None,
    'buyer':   [Sale.customer_name.asc().nullslast(), Sale.id.desc()],
}
SALE_SORT_LABELS = [
    ('newest', 'Newest first'), ('oldest', 'Oldest first'),
    ('largest', 'Largest value'), ('buyer', 'Buyer name'),
]
SETTLEMENT_FILTERS = ['paid', 'partial', 'credit']

CUSTOMER_SORTS = {
    'name':   [Customer.name.asc()],
    'newest': [Customer.id.desc()],
}
CUSTOMER_SORT_LABELS = [('name', 'Name (A-Z)'), ('newest', 'Recently added')]


@sales_bp.route('/')
@login_required
@permission_required('sales.view')
def list_sales():
    page = request.args.get('page', 1, type=int)
    business_id = current_user.business_id
    term = listing.search_term()
    settlement = listing.filter_value('settlement', SETTLEMENT_FILTERS)
    sort = listing.sort_key(SALE_SORTS, 'newest')

    # The list shows each sale's lines and customer, so load them with the sales
    # rather than firing a query per row.
    query = (
        Sale.query.filter_by(business_id=business_id)
        .options(joinedload(Sale.items).joinedload(SaleItem.product),
                 joinedload(Sale.customer))
    )

    if term:
        # Searching a sale means searching who bought it, which lives in two
        # places, plus the invoice number people read off a printed copy.
        query = query.outerjoin(Customer, Sale.customer_id == Customer.id)
        conditions = [Customer.name.ilike(f'%{term}%'),
                      Sale.customer_name.ilike(f'%{term}%'),
                      Sale.customer_phone.ilike(f'%{term}%')]
        if term.lstrip('#').isdigit():
            conditions.append(Sale.id == int(term.lstrip('#')))
        query = query.filter(db.or_(*conditions))

    totals = credit_service.sale_value_subquery(business_id)
    paid = credit_service.sale_paid_subquery(business_id)
    if settlement or sort == 'largest':
        query = (query.outerjoin(totals, totals.c.sale_id == Sale.id)
                      .outerjoin(paid, paid.c.sale_id == Sale.id))
    if settlement:
        value = func.coalesce(totals.c.total, 0)
        received = func.coalesce(paid.c.paid, 0)
        if settlement == 'paid':
            query = query.filter(received >= value, value > 0)
        elif settlement == 'partial':
            query = query.filter(received > 0, received < value)
        else:
            query = query.filter(received == 0, value > 0)

    if sort == 'largest':
        query = query.order_by(func.coalesce(totals.c.total, 0).desc(), Sale.id.desc())
    else:
        query = listing.apply_sort(query, SALE_SORTS, sort)

    pagination = query.paginate(page=page, per_page=15, error_out=False)
    return render_template(
        'sales/list.html', sales=pagination.items, pagination=pagination,
        q=term, sort=sort, sort_options=SALE_SORT_LABELS,
        settlement=settlement,
        is_filtered=listing.is_filtered('q', 'settlement'),
    )

def _settle_sale(sale, form):
    """Write the payment implied by the settlement choice. Returns what is owed.

    Businesses without the credit feature always settle in full: without a way to
    see or chase a balance, letting them create one would quietly lose them money.
    """
    from credit.models import Payment, sale_total

    total = sale_total(sale)
    if not limits.has_feature('credit_ledger'):
        choice, received = 'paid', total
    else:
        choice = form.settlement.data or 'paid'
        if choice == 'paid':
            received = total
        elif choice == 'partial':
            received = min(Decimal(form.amount_paid.data or 0), total)
        else:
            received = Decimal('0')

    if received > 0:
        db.session.add(Payment(
            business_id=sale.business_id,
            sale_id=sale.id,
            customer_id=sale.customer_id,
            amount=received,
            method=form.payment_method.data or 'cash',
            reference=(form.payment_reference.data or '').strip() or None,
            paid_on=sale.sale_date,
            recorded_by=current_user.id,
        ))

    owing = total - received
    if owing > 0:
        audit.log('sale.on_credit', entity_type='sale', entity_id=sale.id,
                  total=str(total), paid=str(received), owing=str(owing),
                  customer=sale.customer.name if sale.customer else None)
    return owing


@sales_bp.route('/pending')
@login_required
@permission_required('sales.create')
@requires_feature('offline')
def pending_sales():
    """Sales recorded on this device and not yet synced.

    The server knows nothing about them - they live in the browser's IndexedDB
    until they sync, which is the whole point. This route serves the shell and
    the page fills it from the device.
    """
    return render_template('sales/pending.html')


@sales_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('sales.create')
def add_sale():
    form = SaleForm()
    # One query, not two. The same list feeds the choices and the price map.
    # Active only. This listed every product the business had ever created, so
    # the sale form offered lines the owner had deliberately retired - and, once
    # a downgrade started switching products off to fit a plan, every one of
    # those too. A cap that the sell page ignores is not a cap.
    catalogue = (Product.query
                 .filter(Product.business_id == current_user.business_id,
                         Product.is_active.isnot(False))
                 .all())
    product_choices = [(str(p.id), p.name) for p in catalogue]

    # Everything the sale form needs to know about a product, in one variable.
    # Deliberately not a second context variable: this template is rendered from
    # five places in this route, and the purchase order page has already shipped
    # a bug where one of those paths forgot a variable the template required.
    may_convert = limits.has_feature('uom_conversion')
    product_prices = {
        str(p.id): {
            'price': float(p.unit_price or 0),
            'pack_price': float(uom.price_for(p, uom.PURCHASE)),
            'per': uom.factor(p),
            'base': p.base_uom or 'pcs',
            'pack': p.purchase_uom or 'unit',
            # What this product may actually be rung up in, already filtered by
            # the plan - so the control cannot offer what the server refuses.
            'units': uom.sell_units(p) if may_convert else [uom.BASE],
            # Which of them the form should open on. A wholesaler reaches for a
            # carton first; making them pick it every time is the same mistake
            # as asking them what a bottle costs.
            'default': uom.default_sell_unit(p) if may_convert else uom.BASE,
        }
        for p in catalogue
    }
    for item_form in form.items:
        item_form.form.product_id.choices = product_choices  # type: ignore
    form.customer_id.choices = [('0', 'No Customer')] + [(str(c.id), c.name) for c in Customer.query.filter_by(business_id=current_user.business_id).order_by(Customer.name)]  # type: ignore
    if form.validate_on_submit():
        customer_id = int(form.customer_id.data) if form.customer_id.data and form.customer_id.data != '0' else None
        customer_name = form.customer_name.data.strip() if form.customer_name.data else None
        customer_phone = form.customer_phone.data.strip() if form.customer_phone.data else None
        try:
            sale = Sale()
            sale.business_id = current_user.business_id
            sale.sale_date = form.sale_date.data or date.today()
            sale.customer_id = customer_id
            # Only meaningful for a walk-in; a registered customer carries their
            # own name and storing a second copy would let the two disagree.
            sale.customer_name = None if customer_id else customer_name
            sale.customer_phone = None if customer_id else customer_phone
            db.session.add(sale)
            deviations = []
            # Save all sale items
            for item_form in form.items:
                # Re-checked here rather than trusting the choice list: the id
                # is posted, and a posted id is not evidence. Same rule the
                # unit and the price already follow on this route.
                product = (Product.query
                           .filter(Product.id == int(item_form.product_id.data),
                                   Product.business_id == current_user.business_id,
                                   Product.is_active.isnot(False))
                           .first())
                if not product:
                    db.session.rollback()
                    flash('One of the selected products is not available.', 'danger')
                    return render_template('sales/add.html', form=form, product_prices=product_prices,
                               can_discount=current_user.can('sales.discount'),
                               max_discount=current_user.business.max_discount_percent)

                # Which unit this line was rung up in. Gated three times, in
                # this order and for the same reasons purchases/routes.py does
                # it: the plan may not include conversion, the product may not
                # have one, and the business may not sell that unit. Hiding the
                # selector enforces nothing - a hand-posted unit must not buy a
                # conversion nobody paid for.
                sold_unit = uom.BASE
                if limits.has_feature('uom_conversion'):
                    asked = item_form.sell_unit.data or uom.BASE
                    # Falling back to the product's own default rather than to
                    # singles. A product sold only by the carton, posted without
                    # a unit - no script running, a trimmed form - used to sell
                    # as loose bottles at a bottle's price. default_sell_unit
                    # can only ever return a unit sell_units already allows, so
                    # this cannot buy a conversion the plan or the product
                    # refuses; that gate is still the one above.
                    sold_unit = (asked if asked in uom.sell_units(product)
                                 else uom.default_sell_unit(product))

                typed_quantity = item_form.quantity.data
                base_quantity = uom.to_base(product, typed_quantity, sold_unit)

                # The server decides the price. A posted value is only a request:
                # readonly in the template never stopped an edited POST (F-07).
                charged, deviation = pricing.resolve(
                    product=product,
                    business=current_user.business,
                    requested_price=item_form.price_at_sale.data,
                    may_discount=current_user.can('sales.discount'),
                    unit=sold_unit,
                )

                sale_item = SaleItem()
                sale_item.product_id = product.id
                # Base units on the row; what was rung up alongside it, so the
                # invoice can say "2 cartons" without any sum having to know.
                sale_item.quantity = base_quantity
                sale_item.sell_unit = sold_unit
                sale_item.sold_quantity = typed_quantity
                sale_item.price_at_sale = uom.price_to_base(product, charged, sold_unit)
                # Keep what it listed for, so a discount is still visible on the
                # invoice and in reports long after the product is repriced.
                sale_item.list_price = uom.price_to_base(
                    product, uom.price_for(product, sold_unit), sold_unit)
                sale.items.append(sale_item)
                deviations.append((product, deviation))

                # Stock moves only through the service, which draws down FEFO and
                # refreshes the cached quantity from the batch sum (F-12).
                stock.deduct_fefo(product, base_quantity, current_user.business_id)

            db.session.flush()   # sale.id, needed by the audit entries
            for product, deviation in deviations:
                pricing.record_deviation(sale, product, deviation)

            owing = _settle_sale(sale, form)

            db.session.commit()
            if owing > 0:
                flash(f'Sale recorded. ₵{owing:.2f} outstanding.', 'success')
            else:
                flash('Sale recorded and paid in full.', 'success')
            return redirect(url_for('sales.sale_invoice', sale_id=sale.id))
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
    term = listing.search_term()
    sort = listing.sort_key(CUSTOMER_SORTS, 'name')
    query = listing.apply_search(
        Customer.query.filter_by(business_id=current_user.business_id), term,
        [Customer.name, Customer.phone, Customer.email, Customer.address])
    customers = listing.apply_sort(query, CUSTOMER_SORTS, sort).all()
    return render_template('sales/customers.html', customers=customers,
                           q=term, sort=sort, sort_options=CUSTOMER_SORT_LABELS,
                           is_filtered=listing.is_filtered('q'))

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
    audit.log('customer.delete', entity_type='customer', entity_id=customer.id, name=customer.name)
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

    sales = (Sale.query
             .filter(Sale.id.in_(ids), Sale.business_id == current_user.business_id)
             .options(joinedload(Sale.items).joinedload(SaleItem.product))
             .all())
    if action == 'delete':
        try:
            for sale in sales:
                audit.log('sale.void', entity_type='sale', entity_id=sale.id,
                          sale_date=str(sale.sale_date),
                          lines=[{'sku': i.product.sku if i.product else None,
                                  'qty': i.quantity, 'price': str(i.price_at_sale)}
                                 for i in sale.items])
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
    sale = (Sale.query
            .filter_by(id=sale_id, business_id=current_user.business_id)
            .options(joinedload(Sale.items).joinedload(SaleItem.product),
                     joinedload(Sale.customer))
            .first_or_404())
    # Read from the sale, not the query string: a name in a URL survives one
    # redirect, leaks into logs and browser history, and is gone on reload.
    return render_template('sales/invoice.html', sale=sale,
                           customer_name=sale.customer_name)

@sales_bp.route('/bulk_print_invoices')
@login_required
@permission_required('sales.view')
def bulk_print_invoices():
    ids = request.args.get('ids', '')
    id_list = [int(i) for i in ids.split(',') if i.isdigit()]
    sales = Sale.query.filter(Sale.id.in_(id_list), Sale.business_id == current_user.business_id).all()
    return render_template('sales/bulk_invoices.html', sales=sales)