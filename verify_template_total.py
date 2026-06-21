from app import create_app
from flask import render_template
from sales.models import Sale

app = create_app()
app.config['TESTING'] = True

with app.app_context():
    sales = Sale.query.limit(1).all()
    if not sales:
        print("No sales, skipping verification.")
    else:
        sale = sales[0]
        # Calculate expected total
        expected_total = sum(item.price_at_sale * item.quantity for item in sale.items)
        print(f"Expected total: {expected_total}")
        
        # Render template
        with app.test_request_context():
            rendered = render_template('sales/invoice.html', sale=sale)
        
        # Check if expected total is present in rendered string
        # This is a basic check.
        if f'₵{expected_total}' in rendered or f'{expected_total}0' in rendered: # handle float formatting loosely
             print("SUCCESS: Expected total found in rendered invoice.")
        else:
             print("FAILURE: Expected total NOT found in rendered invoice.")
             # print(rendered)
