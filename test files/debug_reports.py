from app import create_app
from extensions import db
from sales.models import Sale, SaleItem
from products.models import Product

app = create_app()

with app.app_context():
    print("Querying Sales joined with SaleItem...")
    try:
        # Simulate the query in reports/routes.py
        query = Sale.query.join(SaleItem)
        print(f"Query constructed: {query}")
        result = query.first()
        print(f"First result: {result}")
        
        # Simulate loop
        sales = Sale.query.all()
        for sale in sales:
            for item in sale.items:
                print(f"Sale {sale.id} Item product: {item.product.name}")
                
    except Exception as e:
        print(f"Error caught: {e}")
        import traceback
        traceback.print_exc()
