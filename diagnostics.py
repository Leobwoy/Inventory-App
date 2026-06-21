from app import create_app
from extensions import db
from products.models import Product
from sqlalchemy import text

app = create_app()
with app.app_context():
    try:
        # Test DB connection
        db.session.execute(text('SELECT 1'))
        print("Database connection: SUCCESS")
        
        # Check models
        product_count = Product.query.count()
        print(f"Product model check: SUCCESS (Found {product_count} products)")
        
    except Exception as e:
        print(f"DIAGNOSTIC FAILED: {str(e)}")
