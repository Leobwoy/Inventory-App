from flask import render_template, redirect, url_for, flash, request
from . import purchases_bp
from .models import Purchase
from products.models import Product, Supplier
from .forms import PurchaseForm
from extensions import db
from datetime import date
import pandas as pd
from flask import send_file
import io

@purchases_bp.route('/')
def list_purchases():
    purchases = Purchase.query.order_by(Purchase.purchase_date.desc()).all()
    return render_template('purchases/list.html', purchases=purchases)

@purchases_bp.route('/add', methods=['GET', 'POST'])
def add_purchase():
    form = PurchaseForm()
    form.product_id.choices = [(p.id, p.name) for p in Product.query.all()]
    form.supplier_id.choices = [(0, 'No Supplier')] + [(s.id, s.name) for s in Supplier.query.order_by(Supplier.name)]
    if form.validate_on_submit():
        product = Product.query.get(form.product_id.data)
        supplier = Supplier.query.get(form.supplier_id.data) if form.supplier_id.data else None
        purchase = Purchase(
            product_id=product.id,
            quantity=form.quantity.data,
            purchase_price=form.purchase_price.data,
            supplier=supplier,
            purchase_date=form.purchase_date.data or date.today()
        )
        product.quantity_in_stock += form.quantity.data
        db.session.add(purchase)
        db.session.commit()
        flash('Purchase recorded!', 'success')
        return redirect(url_for('purchases.list_purchases'))
    return render_template('purchases/add.html', form=form)

@purchases_bp.route('/bulk_action', methods=['POST'])
def bulk_action():
    action = request.form.get('action')
    ids = request.form.getlist('purchase_ids')
    if not ids:
        flash('No purchases selected.', 'warning')
        return redirect(url_for('purchases.list_purchases'))
    purchases = Purchase.query.filter(Purchase.id.in_(ids)).all()
    if action == 'delete':
        for purchase in purchases:
            db.session.delete(purchase)
        db.session.commit()
        flash(f'{len(purchases)} purchases deleted.', 'success')
        return redirect(url_for('purchases.list_purchases'))
    elif action == 'export_csv':
        headers = ['Date', 'Product', 'Quantity', 'Purchase Price', 'Supplier', 'Total']
        data = [[p.purchase_date, p.product.name, p.quantity, float(p.purchase_price), p.supplier.name if p.supplier else '', float(p.purchase_price * p.quantity)] for p in purchases]
        df = pd.DataFrame(data, columns=headers)
        output = pd.io.common.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype='text/csv',
            as_attachment=True,
            download_name='purchases_bulk_export.csv'
        )
    elif action == 'export_excel':
        headers = ['Date', 'Product', 'Quantity', 'Purchase Price', 'Supplier', 'Total']
        data = [[p.purchase_date, p.product.name, p.quantity, float(p.purchase_price), p.supplier.name if p.supplier else '', float(p.purchase_price * p.quantity)] for p in purchases]
        df = pd.DataFrame(data, columns=headers)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='purchases_bulk_export.xlsx'
        )
    else:
        flash('Invalid bulk action.', 'danger')
        return redirect(url_for('purchases.list_purchases')) 