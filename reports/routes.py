from flask import render_template, request, make_response
from . import reports_bp
from sales.models import Sale, SaleItem
from purchases.models import Purchase
from products.models import Product
from extensions import db
from datetime import datetime
import io
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
import pandas as pd

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
def sales_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    product_id = request.args.get('product_id', type=int)
    query = Sale.query
    if start_date:
        query = query.filter(Sale.sale_date >= start_date)
    if end_date:
        query = query.filter(Sale.sale_date <= end_date)
    if product_id:
        query = query.join(SaleItem).filter(SaleItem.product_id == product_id)
    sales = query.order_by(Sale.sale_date.desc()).all()
    products = Product.query.all()
    
    total = 0
    data_rows = []
    
    for sale in sales:
        for item in sale.items:
            # If filtering by product, we should only include relevant items or all?
            # Usually filtering by product means "sales containing this product" or "only this product's text".
            # For a report on a specific product, we usually want to show only that product's lines.
            if product_id and item.product_id != product_id:
                continue
                
            total += item.price_at_sale * item.quantity
            data_rows.append([
                str(sale.sale_date), 
                item.product.name, 
                item.quantity, 
                float(item.price_at_sale), 
                float(item.price_at_sale * item.quantity)
            ])
            
    headers = ['Date', 'Product', 'Quantity', 'Unit Price', 'Total']
    data_rows.append(['', '', '', 'Summary Total', float(total)])
    export = request.args.get('export')
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
def purchases_report():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    product_id = request.args.get('product_id', type=int)
    query = Purchase.query
    if start_date:
        query = query.filter(Purchase.purchase_date >= start_date)
    if end_date:
        query = query.filter(Purchase.purchase_date <= end_date)
    if product_id:
        query = query.filter(Purchase.product_id == product_id)
    purchases = query.order_by(Purchase.purchase_date.desc()).all()
    total = sum(purchase.purchase_price * purchase.quantity for purchase in purchases)
    products = Product.query.all()
    headers = ['Date', 'Product', 'Quantity', 'Purchase Price', 'Supplier', 'Total']
    data_rows = [[str(purchase.purchase_date), purchase.product.name, purchase.quantity, float(purchase.purchase_price), purchase.supplier.name if purchase.supplier else '', float(purchase.purchase_price * purchase.quantity)] for purchase in purchases]
    data_rows.append(['', '', '', '', 'Summary Total', float(total)])
    export = request.args.get('export')
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
def stock_report():
    products = Product.query.all()
    headers = ['Name', 'SKU', 'Description', 'Unit Price', 'Quantity in Stock']
    data_rows = [[p.name, p.sku, p.description, float(p.unit_price), p.quantity_in_stock] for p in products]
    export = request.args.get('export')
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