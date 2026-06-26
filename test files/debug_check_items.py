from app import create_app
from extensions import db
from sales.models import Sale, SaleItem

app = create_app()
with app.app_context():
    sales = Sale.query.limit(5).all()
    print(f"Found {len(sales)} sales.")
    for sale in sales:
        print(f"Sale ID: {sale.id}")
        # items is a list-like instrumented list
        print(f"Items type: {type(sale.items)}")
        for i, item in enumerate(sale.items):
            print(f"  Item {i} type: {type(item)}")
            print(f"  Item {i} repr: {item}")
            if hasattr(item, 'price_at_sale'):
                 print(f"  Price: {item.price_at_sale}")
            else:
                 print("  NO price_at_sale attribute!")
