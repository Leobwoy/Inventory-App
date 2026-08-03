from flask import render_template, redirect, url_for, flash, request, current_app
from . import purchases_bp
from .models import PurchaseOrder, PurchaseOrderItem, StockBatch
from products.models import Product, Supplier
from .forms import PurchaseOrderForm, GoodsReceiptForm
from extensions import db
from datetime import date, timedelta
import pandas as pd
from flask import send_file
import io
from flask_login import login_required, current_user
from auth.decorators import permission_required
from services import audit, stock

@purchases_bp.route('/')
@login_required
@permission_required('purchase_orders.view')
def list_purchases():
    page = request.args.get('page', 1, type=int)
    pagination = PurchaseOrder.query.filter_by(business_id=current_user.business_id).order_by(PurchaseOrder.order_date.desc()).paginate(page=page, per_page=15, error_out=False)
    return render_template('purchases/list.html', purchase_orders=pagination.items, pagination=pagination)

@purchases_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('purchase_orders.create')
def add_purchase():
    form = PurchaseOrderForm()
    supplier_choices = [(0, 'No Supplier')] + [(s.id, s.name) for s in Supplier.query.filter_by(business_id=current_user.business_id).order_by(Supplier.name)]
    form.supplier_id.choices = supplier_choices
    
    product_choices = [(p.id, p.name) for p in Product.query.filter_by(business_id=current_user.business_id).all()]
    for item in form.items:
        item.form.product_id.choices = product_choices

    if form.validate_on_submit():
        try:
            supplier = Supplier.query.filter_by(id=form.supplier_id.data, business_id=current_user.business_id).first() if form.supplier_id.data and form.supplier_id.data != 0 else None
            po = PurchaseOrder(
                business_id=current_user.business_id,
                supplier_id=supplier.id if supplier else None,
                status='ordered',
                order_date=form.order_date.data or date.today(),
                expected_date=form.expected_date.data,
                created_by=current_user.id
            )
            db.session.add(po)
            db.session.flush() # get po.id
            
            for item_form in form.items:
                product = Product.query.filter_by(id=item_form.product_id.data, business_id=current_user.business_id).first()
                if product:
                    poi = PurchaseOrderItem(
                        po_id=po.id,
                        product_id=product.id,
                        quantity_ordered=item_form.quantity_ordered.data,
                        quantity_received=0,
                        unit_cost=item_form.unit_cost.data
                    )
                    db.session.add(poi)
            
            db.session.commit()
            flash('Purchase Order created!', 'success')
            return redirect(url_for('purchases.list_purchases'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('%s failed', request.endpoint)
            flash('Something went wrong and nothing was saved. Please try again.', 'danger')
    return render_template('purchases/add.html', form=form)

def _parse_date(raw):
    """Parse an ISO date from a form field, returning None for blank or malformed input."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None


@purchases_bp.route('/receive/<int:po_id>', methods=['GET', 'POST'])
@login_required
@permission_required('purchase_orders.receive')
def receive_po(po_id):
    po = PurchaseOrder.query.filter_by(id=po_id, business_id=current_user.business_id).first_or_404()
    if po.status == 'received':
        flash('This order is already fully received.', 'warning')
        return redirect(url_for('purchases.list_purchases'))
        
    if request.method == 'POST':
        received_on = _parse_date(request.form.get('received_date')) or date.today()
        if received_on > date.today():
            flash('The receipt date cannot be in the future.', 'danger')
            return render_template('purchases/receive.html', po=po, today=date.today(),
                                   earliest_expiry=date.today() + timedelta(days=1))

        try:
            # Lock the lines for the rest of this transaction. quantity_received
            # is read to compute `outstanding` and written further down; without
            # the lock two concurrent receipts both see the same outstanding,
            # both pass the check, and the order takes in more than was ordered.
            locked_items = PurchaseOrderItem.query.filter_by(po_id=po.id) \
                .order_by(PurchaseOrderItem.id).with_for_update().all()

            errors, receipts = [], []
            for item in locked_items:
                outstanding = item.quantity_ordered - (item.quantity_received or 0)
                if outstanding <= 0:
                    continue

                if not item.product:
                    # stock.receive dereferences product.id, so a line with no
                    # product would surface as an opaque AttributeError.
                    errors.append(f'Line {item.id} has no product and cannot be received.')
                    continue

                qty = request.form.get(f'qty_{item.id}', type=int) or 0
                if qty <= 0:
                    continue          # this line simply is not being received now
                if qty > outstanding:
                    errors.append(
                        f'{item.product.name}: cannot receive {qty}, '
                        f'only {outstanding} outstanding.'
                    )
                    continue

                expiry = _parse_date(request.form.get(f'expiry_{item.id}'))
                if expiry and expiry <= received_on:
                    errors.append(
                        f'{item.product.name}: expiry date must be '
                        'after the receipt date.'
                    )
                    continue

                receipts.append((item, qty, request.form.get(f'batch_{item.id}', '').strip(), expiry))

            if errors:
                for message in errors:
                    flash(message, 'danger')
                return render_template('purchases/receive.html', po=po, today=date.today(),
                                   earliest_expiry=date.today() + timedelta(days=1))

            if not receipts:
                flash('Enter a quantity for at least one line to receive.', 'warning')
                return render_template('purchases/receive.html', po=po, today=date.today(),
                                   earliest_expiry=date.today() + timedelta(days=1))

            for item, qty, batch_number, expiry in receipts:
                item.quantity_received = (item.quantity_received or 0) + qty
                # Stock enters only through the service, which creates the batch and
                # refreshes the cached quantity from the batch sum (F-12).
                stock.receive(
                    product=item.product,
                    quantity=qty,
                    business_id=current_user.business_id,
                    received_date=received_on,
                    # Sequence per PO line, so a second delivery against the same
                    # line does not reuse the first batch's number.
                    batch_number=batch_number or (
                        f'PO{po.id}-L{item.id}-R'
                        f'{StockBatch.query.filter_by(po_item_id=item.id).count() + 1}'
                    ),
                    expiry_date=expiry,
                    po_item_id=item.id,
                )

            # Fully received only when every line is satisfied; otherwise the PO
            # stays open so the rest can be received later. This status could
            # never occur before, because receipt was all-or-nothing.
            fully = all((i.quantity_received or 0) >= i.quantity_ordered for i in locked_items)
            po.status = 'received' if fully else 'partially_received'

            audit.log('purchase_order.receive', entity_type='purchase_order', entity_id=po.id,
                      received_on=str(received_on), status=po.status,
                      lines=[{'sku': i.product.sku, 'qty': q,
                              'batch': b or None, 'expiry': str(e) if e else None}
                             for i, q, b, e in receipts])

            db.session.commit()
            total = sum(qty for _i, qty, _b, _e in receipts)
            flash(
                f'Received {total} unit(s) across {len(receipts)} line(s). '
                + ('Order complete.' if fully else 'Order remains open for the balance.'),
                'success',
            )
            return redirect(url_for('purchases.list_purchases'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('%s failed', request.endpoint)
            flash('Something went wrong and nothing was saved. Please try again.', 'danger')

    return render_template('purchases/receive.html', po=po, today=date.today(),
                                   earliest_expiry=date.today() + timedelta(days=1))

@purchases_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('purchase_ids')
    if not ids:
        flash('No Purchase Orders selected.', 'warning')
        return redirect(url_for('purchases.list_purchases'))
    # Checked per action, not on the route: one endpoint, several privilege levels.
    # Deleting a PO destroys spend history, so it needs approval rights.
    required = {'delete': 'purchase_orders.approve',
                'export_csv': 'reports.export'}.get(action)
    if not required or not current_user.can(required):
        flash('You do not have permission to do that.', 'danger')
        return redirect(url_for('purchases.list_purchases'))

    pos = PurchaseOrder.query.filter(PurchaseOrder.id.in_(ids), PurchaseOrder.business_id == current_user.business_id).all()
    if action == 'delete':
        try:
            for po in pos:
                audit.log('purchase_order.delete', entity_type='purchase_order', entity_id=po.id,
                          status=po.status, supplier=po.supplier.name if po.supplier else None)
                db.session.delete(po)
            db.session.commit()
            flash(f'{len(pos)} purchase orders deleted.', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('%s bulk delete failed', request.endpoint)
            flash('Something went wrong and nothing was deleted.', 'danger')
        return redirect(url_for('purchases.list_purchases'))
    elif action == 'export_csv':
        headers = ['PO ID', 'Date', 'Supplier', 'Status']
        data = [[p.id, p.order_date, p.supplier.name if p.supplier_id else '', p.status] for p in pos]
        df = pd.DataFrame(data, columns=headers)
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='purchase_orders_bulk_export.csv'
        )
    else:
        flash('Invalid bulk action.', 'danger')
        return redirect(url_for('purchases.list_purchases'))