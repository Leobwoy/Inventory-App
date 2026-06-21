from app import create_app
from extensions import db

print("Starting database initialization...")
app = create_app()
with app.app_context():
    print("Creating tables (if they do not exist)...")
    db.create_all()
    print("Database initialization successful!")
