from flask import render_template, request, make_response, flash
from . import reports_bp
from sales.models import Sale, SaleItem
from purchases.models import PurchaseOrder, PurchaseOrderItem
from products.models import Product
from extensions import db
from sqlalchemy.orm import joinedload
from datetime import datetime
import io
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
import pandas as pd
from flask_login import login_required, current_user
from auth.decorators import permission_required
from services import uom


def _order_view(product, *base_quantities):
    """Which unit a purchase line's numbers should be shown in.

    Packs, normally: orders are placed and received in cartons, so the figures
    divide exactly. A row that does *not* divide exactly falls back to singles
    for every column, rather than reporting whole cartons and quietly dropping
    the remainder - a report that loses stock is worse than one using a less
    convenient unit, and legacy rows predate the pack-only ordering rule.
    """
    if product is None or not uom.has_conversion(product):
        return uom.BASE
    per = uom.factor(product)
    if any(int(q or 0) % per for q in base_quantities):
        return uom.BASE
    return uom.PURCHASE


def _in_units(product, base_quantity, unit):
    """A stored base quantity expressed in `unit`."""
    base_quantity = int(base_quantity or 0)
    if unit != uom.PURCHASE or product is None:
        return base_quantity
    return base_quantity // uom.factor(product)


def _cost_in_units(product, base_cost, unit):
    """A stored per-single cost expressed per `unit`."""
    if unit != uom.PURCHASE or product is None:
        return base_cost
    return uom.cost_per_purchase_unit(product, base_cost)


def generate_pdf_report(title, headers, data_rows):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    width, height = landscape(letter)
    c.setFont('Helvetica-Bold', 16)
    c.drawString(30, height - 40, title)
    c.setFont('Helvetica', 10)
    table_data = [headers] + data_rows
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    table_width, table_height = table.wrapOn(c, width - 60, height - 100)
    table.drawOn(c, 30, height - 60 - table_height)
    c.save()
    buffer.seek(0)
    return buffer

def export_to_excel(headers, data_rows, filename):
    df = pd.DataFrame(data_rows, columns=headers)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

def export_to_csv(headers, data_rows, filename):
    df = pd.DataFrame(data_rows, columns=headers)
    output = io.StringIO()
    df.to_csv(output, index=False)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response

@reports_bp.route('/sales')
@login_required
@permission_required('reports.view')
def sales_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    product_id = request.args.get('product_id', type=int)
    # The template walks sale.items five times per row and reads item.product on
    # each. Without eager loading that is two queries per sale plus one per line,
    # and the report has no default date bound - so the default view is the worst
    # case (F-15).
    query = Sale.query.filter_by(business_id=current_user.business_id).options(
        joinedload(Sale.items).joinedload(SaleItem.product),
        joinedload(Sale.customer),
    )
    if start_date:
        query = query.filter(Sale.sale_date >= start_date)
    if end_date:
        query = query.filter(Sale.sale_date <= end_date)
    if product_id:
        query = query.join(SaleItem).filter(SaleItem.product_id == product_id)
    sales = query.order_by(Sale.sale_date.desc()).all()
    products = Product.query.filter_by(business_id=current_user.business_id).all()
    
    total = 0
    data_rows = []
    
    for sale in sales:
        for item in sale.items:
            if product_id and item.product_id != product_id:
                continue
                
            total += item.price_at_sale * item.quantity
            # Numbers stay numeric and the unit gets a column of its own. A
            # spreadsheet cell holding "2 cartons" cannot be summed, and a
            # column headed "Quantity" holding 48 for a sale of 2 cartons is
            # the round trip that does not close.
            sold, sold_unit = item.sold_as
            data_rows.append([
                str(sale.sale_date),
                item.product.name,
                sold_unit,
                sold,
                float(item.price_per_sold_unit),
                float(item.price_at_sale * item.quantity)
            ])

    headers = ['Date', 'Product', 'Sold by', 'Quantity', 'Price each', 'Total']
    data_rows.append(['', '', '', '', 'Summary Total', float(total)])
    export = request.args.get('export')
    if export and not current_user.can('reports.export'):
        flash('You do not have permission to export reports.', 'danger')
        export = None
    if export == 'pdf':
        pdf_buffer = generate_pdf_report('Sales Report', headers, data_rows)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline; filename=sales_report.pdf'
        return response
    if export == 'excel':
        return export_to_excel(headers, data_rows, 'sales_report.xlsx')
    if export == 'csv':
        return export_to_csv(headers, data_rows, 'sales_report.csv')
    return render_template('reports/sales_report.html', sales=sales, total=total, products=products, filters=request.args)

@reports_bp.route('/purchases')
@login_required
@permission_required('reports.view')
def purchases_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    product_id = request.args.get('product_id', type=int)

    # Reads PurchaseOrderItem, not the legacy Purchase table. Nothing has written a
    # Purchase row since the PO lifecycle landed, so this report was always empty (F-04).
    query = (
        PurchaseOrderItem.query
        .join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id)
        .filter(PurchaseOrder.business_id == current_user.business_id)
        .options(
            joinedload(PurchaseOrderItem.product),
            joinedload(PurchaseOrderItem.purchase_order).joinedload(PurchaseOrder.supplier),
        )
    )
    if start_date:
        query = query.filter(PurchaseOrder.order_date >= start_date)
    if end_date:
        query = query.filter(PurchaseOrder.order_date <= end_date)
    if product_id:
        query = query.filter(PurchaseOrderItem.product_id == product_id)

    purchases = query.order_by(PurchaseOrder.order_date.desc()).all()
    total = sum((item.unit_cost or 0) * item.quantity_ordered for item in purchases)
    products = Product.query.filter_by(business_id=current_user.business_id).all()
    # An order placed as 10 cartons exported as "Ordered: 240", which is the
    # round trip that was already visible to anyone reconciling a delivery note
    # against this sheet. Quantities and the cost beside them are in the unit
    # the order was actually placed in; the line total is unchanged, because
    # cartons x cost-per-carton is the same money as bottles x cost-per-bottle.
    headers = ['Date', 'PO', 'Product', 'Ordered by', 'Ordered', 'Received',
               'Cost each', 'Supplier', 'Status', 'Total']
    data_rows = []
    for item in purchases:
        unit = _order_view(item.product, item.quantity_ordered, item.quantity_received)
        data_rows.append([
            str(item.purchase_order.order_date),
            f'PO-{item.po_id}',
            item.product.name if item.product else '',
            uom.unit_label(item.product, unit) if item.product else '',
            _in_units(item.product, item.quantity_ordered, unit),
            _in_units(item.product, item.quantity_received or 0, unit),
            float(_cost_in_units(item.product, item.unit_cost or 0, unit)),
            item.purchase_order.supplier.name if item.purchase_order.supplier else '',
            item.purchase_order.status,
            float((item.unit_cost or 0) * item.quantity_ordered),
        ])
    data_rows.append(['', '', '', '', '', '', '', '', 'Summary Total', float(total)])
    export = request.args.get('export')
    if export and not current_user.can('reports.export'):
        flash('You do not have permission to export reports.', 'danger')
        export = None
    if export == 'pdf':
        pdf_buffer = generate_pdf_report('Purchases Report', headers, data_rows)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline; filename=purchases_report.pdf'
        return response
    if export == 'excel':
        return export_to_excel(headers, data_rows, 'purchases_report.xlsx')
    if export == 'csv':
        return export_to_csv(headers, data_rows, 'purchases_report.csv')
    return render_template('reports/purchases_report.html', purchases=purchases, total=total, products=products, filters=request.args)

@reports_bp.route('/stock')
@login_required
@permission_required('reports.view')
def stock_report():
    products = Product.query.filter_by(business_id=current_user.business_id).all()
    # Whole packs and the loose remainder in separate numeric columns, plus the
    # singles total to check a physical count against. One column reading
    # "13 cartons + 6 bottles" would be unsummable.
    headers = ['Name', 'SKU', 'Description', 'Sold by', 'Price each',
               'In stock', 'Loose singles', 'Singles in total']
    data_rows = []
    for p in products:
        whole, loose = uom.split(p, p.quantity_in_stock)
        data_rows.append([
            p.name, p.sku, p.description, uom.packing(p),
            float(uom.price_for(p, uom.PURCHASE if uom.has_conversion(p) else uom.BASE)),
            whole if uom.has_conversion(p) else p.quantity_in_stock,
            loose if uom.has_conversion(p) else 0,
            p.quantity_in_stock,
        ])
    export = request.args.get('export')
    if export and not current_user.can('reports.export'):
        flash('You do not have permission to export reports.', 'danger')
        export = None
    if export == 'pdf':
        pdf_buffer = generate_pdf_report('Stock Report', headers, data_rows)
        response = make_response(pdf_buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = 'inline; filename=stock_report.pdf'
        return response
    if export == 'excel':
        return export_to_excel(headers, data_rows, 'stock_report.xlsx')
    if export == 'csv':
        return export_to_csv(headers, data_rows, 'stock_report.csv')
    return render_template('reports/stock_report.html', products=products)