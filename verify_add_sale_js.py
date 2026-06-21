from app import create_app
from sales.forms import SaleForm, SaleItemForm
from werkzeug.datastructures import MultiDict
import sys

app = create_app()
app.config['WTF_CSRF_ENABLED'] = False

with app.app_context():
    print("Verifying SaleForm with multiple items...")
    # Simulate form data for 2 items
    form_data = MultiDict([
        ('sale_date', '2023-01-01'),
        ('customer_id', '0'),
        ('items-0-product_id', '1'),
        ('items-0-quantity', '2'),
        ('items-0-price_at_sale', '10.00'),
        ('items-1-product_id', '2'),
        ('items-1-quantity', '3'),
        ('items-1-price_at_sale', '20.00'),
    ])
    
    SaleForm.items.kwargs['min_entries'] = 0 # Avoid auto-creation issues    
    form = SaleForm(formdata=form_data)
    
    # Iterate over the bound fields in the FieldList
    for item_form in form.items:
        # Access the internal form of the specific entry via .form property
        item_form.form.product_id.choices = [('1', 'Product 1'), ('2', 'Product 2')]

    if form.validate():
        print(f"SUCCESS: Form validated.")
        print(f"Items count: {len(form.items)}")
        if len(form.items) == 2:
             print("SUCCESS: Form captured 2 items.")
        else:
             print(f"FAILURE: Form captured {len(form.items)} items, expected 2.")
             sys.exit(1)
    else:
        print("FAILURE: Form validation failed.")
        print(form.errors)
        sys.exit(1)
