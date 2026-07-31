from flask import render_template, redirect, url_for, flash, request
from . import purchases_bp
from .models import PurchaseOrder, PurchaseOrderItem, StockBatch
from products.models import Product, Supplier
from .forms import PurchaseOrderForm, GoodsReceiptForm
from extensions import db
from datetime import date
import pandas as pd
from flask import send_file
import io
from flask_login import login_required, current_user

@purchases_bp.route('/')
@login_required
def list_purchases():
    page = request.args.get('page', 1, type=int)
    pagination = PurchaseOrder.query.filter_by(business_id=current_user.business_id).order_by(PurchaseOrder.order_date.desc()).paginate(page=page, per_page=15, error_out=False)
    return render_template('purchases/list.html', purchase_orders=pagination.items, pagination=pagination)

@purchases_bp.route('/add', methods=['GET', 'POST'])
@login_required
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
            flash(f'An error occurred: {str(e)}', 'danger')
    return render_template('purchases/add.html', form=form)

@purchases_bp.route('/receive/<int:po_id>', methods=['GET', 'POST'])
@login_required
def receive_po(po_id):
    po = PurchaseOrder.query.filter_by(id=po_id, business_id=current_user.business_id).first_or_404()
    if po.status == 'received':
        flash('This order is already fully received.', 'warning')
        return redirect(url_for('purchases.list_purchases'))
        
    if request.method == 'POST':
        try:
            for item in po.items:
                qty_to_receive = item.quantity_ordered - item.quantity_received
                if qty_to_receive > 0:
                    item.quantity_received += qty_to_receive
                    
                    batch = StockBatch(
                        business_id=current_user.business_id,
                        product_id=item.product_id,
                        po_item_id=item.id,
                        batch_number=f"PO-{po.id}-ITEM-{item.id}",
                        quantity_received=qty_to_receive,
                        quantity_remaining=qty_to_receive,
                        received_date=date.today()
                    )
                    db.session.add(batch)
                    
                    if item.product:
                        item.product.quantity_in_stock += qty_to_receive
            
            po.status = 'received'
            db.session.commit()
            flash('Goods received successfully!', 'success')
            return redirect(url_for('purchases.list_purchases'))
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {str(e)}', 'danger')
            
    return render_template('purchases/receive.html', po=po)

@purchases_bp.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('purchase_ids')
    if not ids:
        flash('No Purchase Orders selected.', 'warning')
        return redirect(url_for('purchases.list_purchases'))
    pos = PurchaseOrder.query.filter(PurchaseOrder.id.in_(ids), PurchaseOrder.business_id == current_user.business_id).all()
    if action == 'delete':
        try:
            for po in pos:
                db.session.delete(po)
            db.session.commit()
            flash(f'{len(pos)} purchase orders deleted.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred during deletion: {str(e)}', 'danger')
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