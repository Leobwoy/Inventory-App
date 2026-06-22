import os
import random
import datetime
from decimal import Decimal
from app import create_app
from extensions import db
from products.models import Category, Supplier, Product
from sales.models import Customer, Sale, SaleItem
from purchases.models import Purchase

def seed():
    app = create_app()
    with app.app_context():
        print("Wiping existing database tables...")
        db.drop_all()
        db.create_all()
        print("Database schema recreated successfully.")

        # 1. Seed Categories
        categories_data = [
            {"name": "Electronics", "description": "Laptops, phones, accessories, and displays"},
            {"name": "Home & Kitchen", "description": "Appliances, blenders, and air purifiers"},
            {"name": "Office & Furniture", "description": "Ergonomic chairs, standing desks, and paper supplies"},
            {"name": "Fitness & Outdoors", "description": "Yoga mats, water bottles, and workout equipment"}
        ]
        
        categories = {}
        for cat_info in categories_data:
            cat = Category(name=cat_info["name"], description=cat_info["description"])
            db.session.add(cat)
            categories[cat_info["name"]] = cat
        db.session.flush() # Populate IDs

        # 2. Seed Suppliers
        suppliers_data = [
            {"name": "Global Tech Solutions Inc.", "contact": "Alice Smith", "phone": "0244-112233", "email": "info@globaltech.com", "address": "Ring Road Central, near Kwame Nkrumah Circle, Accra"},
            {"name": "EcoAppliance Logistics Ltd.", "contact": "Robert Chen", "phone": "0208-223344", "email": "supply@ecoappliance.com", "address": "Liberation Road, Airport Residential Area, Accra"},
            {"name": "Apex Office Wholesalers", "contact": "Sarah Johnson", "phone": "0553-334455", "email": "orders@apexoffice.com", "address": "Commercial Street, near Harbor Area, Takoradi"},
            {"name": "Vigor Sports Supplies Ltd.", "contact": "Kofi Mensah", "phone": "0243-445566", "email": "bulk@vigorsports.com", "address": "Cape Coast - Takoradi Road, near Takoradi Mall, Takoradi"}
        ]

        suppliers = {}
        for sup_info in suppliers_data:
            sup = Supplier(
                name=sup_info["name"],
                contact=sup_info["contact"],
                phone=sup_info["phone"],
                email=sup_info["email"],
                address=sup_info["address"]
            )
            db.session.add(sup)
            suppliers[sup_info["name"]] = sup
        db.session.flush()

        # 3. Seed Products (Wholesale Goods)
        products_setup = [
            # Electronics
            {"name": "ProBook Laptop 15-inch", "sku": "EL-LAP-15", "desc": "High-performance enterprise laptop with 16GB RAM, 512GB SSD.", "price": 850.00, "min_stock": 20, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            {"name": "SmartPhone X-200", "sku": "EL-PHN-X2", "desc": "6.5-inch OLED smartphone with dual-lens camera, 128GB storage.", "price": 650.00, "min_stock": 25, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            {"name": "TabCore 10-inch Tablet", "sku": "EL-TAB-10", "desc": "Android tablet optimized for productivity and business apps.", "price": 320.00, "min_stock": 15, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            {"name": "AeroBuds Wireless Earphones", "sku": "EL-EAR-AB", "desc": "Noise-cancelling Bluetooth earbuds with 24-hour battery life.", "price": 75.00, "min_stock": 30, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            {"name": "PowerGrid Fast Charger 45W", "sku": "EL-CHG-PG", "desc": "Dual-port USB-C wall charger with smart power delivery.", "price": 25.00, "min_stock": 50, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            {"name": "UltraWide Gaming Monitor 34-inch", "sku": "EL-MON-34", "desc": "Curved 34-inch QHD monitor with 144Hz refresh rate.", "price": 450.00, "min_stock": 10, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            {"name": "PulseFit SmartWatch V2", "sku": "EL-WTCH-PF", "desc": "Smart fitness tracker with optical heart rate sensor.", "price": 120.00, "min_stock": 20, "cat": "Electronics", "sup": "Global Tech Solutions Inc."},
            
            # Home & Kitchen
            {"name": "ChefWave Digital Microwave", "sku": "HK-MIC-CW", "desc": "900W digital microwave with 10 power levels, preset functions.", "price": 180.00, "min_stock": 15, "cat": "Home & Kitchen", "sup": "EcoAppliance Logistics Ltd."},
            {"name": "BrewMaster Espresso Machine", "sku": "HK-ESP-BM", "desc": "15-bar pump espresso maker with integrated milk frother.", "price": 299.00, "min_stock": 10, "cat": "Home & Kitchen", "sup": "EcoAppliance Logistics Ltd."},
            {"name": "FrostGuard Smart Refrigerator", "sku": "HK-REF-FG", "desc": "Double-door refrigerator with smart cooling and energy saver.", "price": 1200.00, "min_stock": 5, "cat": "Home & Kitchen", "sup": "EcoAppliance Logistics Ltd."},
            {"name": "NinjaPulse High-Speed Blender", "sku": "HK-BLD-NP", "desc": "1200W professional blender with auto-iQ programs.", "price": 89.00, "min_stock": 20, "cat": "Home & Kitchen", "sup": "EcoAppliance Logistics Ltd."},
            {"name": "CrispToast 4-Slice Toaster", "sku": "HK-TST-CT", "desc": "Stainless steel toaster with wide slots and browning dial.", "price": 45.00, "min_stock": 20, "cat": "Home & Kitchen", "sup": "EcoAppliance Logistics Ltd."},
            {"name": "PureAir Hepa Purifier", "sku": "HK-PUR-PA", "desc": "True HEPA air filter capturing 99.97% of airborne allergens.", "price": 150.00, "min_stock": 15, "cat": "Home & Kitchen", "sup": "EcoAppliance Logistics Ltd."},

            # Office & Furniture
            {"name": "ErgoComfort Office Chair", "sku": "OF-CHR-EC", "desc": "Ergonomic mesh chair with adjustable lumber support and armrests.", "price": 220.00, "min_stock": 15, "cat": "Office & Furniture", "sup": "Apex Office Wholesalers"},
            {"name": "RiseUp Motorized Standing Desk", "sku": "OF-DSK-RU", "desc": "Adjustable height standing desk with dual motor and memory keys.", "price": 450.00, "min_stock": 8, "cat": "Office & Furniture", "sup": "Apex Office Wholesalers"},
            {"name": "MemoBound A5 Journal (Bulk Pack)", "sku": "OF-JRN-MB", "desc": "Pack of 10 ruled A5 notebooks, softcover leatherette.", "price": 15.00, "min_stock": 40, "cat": "Office & Furniture", "sup": "Apex Office Wholesalers"},
            {"name": "UltraPrint A4 Paper Ream", "sku": "OF-PPR-A4", "desc": "High-quality 80gsm white printing paper (box of 5 reams).", "price": 8.00, "min_stock": 100, "cat": "Office & Furniture", "sup": "Apex Office Wholesalers"},
            {"name": "Precision Gel Pens (Box of 24)", "sku": "OF-PEN-GEL", "desc": "Fine point black ink gel pens for daily office use.", "price": 18.00, "min_stock": 50, "cat": "Office & Furniture", "sup": "Apex Office Wholesalers"},
            {"name": "HeavyDuty Metal Stapler", "sku": "OF-STP-HD", "desc": "Full strip desktop stapler, 25-sheet capacity, heavy-duty.", "price": 12.00, "min_stock": 30, "cat": "Office & Furniture", "sup": "Apex Office Wholesalers"},

            # Fitness & Outdoors
            {"name": "FlexiMat TPE Yoga Mat", "sku": "FT-MAT-YM", "desc": "Non-slip eco-friendly TPE yoga mat with alignment lines.", "price": 29.00, "min_stock": 30, "cat": "Fitness & Outdoors", "sup": "Vigor Sports Supplies Ltd."},
            {"name": "IronGrip Dumbbell Set (20kg)", "sku": "FT-DBL-IG", "desc": "Adjustable cast iron dumbbells with secure spinlock collars.", "price": 75.00, "min_stock": 15, "cat": "Fitness & Outdoors", "sup": "Vigor Sports Supplies Ltd."},
            {"name": "HydroPeak Vacuum Water Bottle 1L", "sku": "FT-BTL-HP", "desc": "Double-wall insulated stainless steel flask with straw lid.", "price": 19.00, "min_stock": 45, "cat": "Fitness & Outdoors", "sup": "Vigor Sports Supplies Ltd."},
            {"name": "ResistBand Loop Set (5 levels)", "sku": "FT-BND-RB", "desc": "Premium latex workout resistance bands with storage pouch.", "price": 14.00, "min_stock": 50, "cat": "Fitness & Outdoors", "sup": "Vigor Sports Supplies Ltd."},
            {"name": "ApexTrail Men's Running Shoes", "sku": "FT-SHS-AT", "desc": "Breathable, lightweight trail running shoes with grip soles.", "price": 95.00, "min_stock": 20, "cat": "Fitness & Outdoors", "sup": "Vigor Sports Supplies Ltd."}
        ]

        products = []
        product_supplier_map = {}
        for p_info in products_setup:
            prod = Product(
                name=p_info["name"],
                sku=p_info["sku"],
                description=p_info["desc"],
                unit_price=Decimal(p_info["price"]),
                quantity_in_stock=0, # Will compute and update at the end
                category=categories[p_info["cat"]],
                min_stock_alert=p_info["min_stock"]
            )
            db.session.add(prod)
            products.append(prod)
            product_supplier_map[prod] = suppliers[p_info["sup"]]
        db.session.flush()

        # 4. Seed Customers (Wholesale Retailers)
        customers_data = [
            {"name": "Metro Retail Outlets", "phone": "0244-556677", "email": "procurement@metroretail.com", "address": "Oxford Street, Osu, Accra"},
            {"name": "TechSavvy Distributors", "phone": "0208-667788", "email": "purchasing@techsavvy.com", "address": "Graphic Road, South Industrial Area, Accra"},
            {"name": "National Office Supplies Co.", "phone": "0553-778899", "email": "office@nationalcorp.com", "address": "Axim Road, near Market Circle, Takoradi"},
            {"name": "Active Life Gyms & Fitness", "phone": "0243-889900", "email": "facilities@activelifegym.com", "address": "Boundary Road, East Legon, Accra"},
            {"name": "General Goods Emporium", "phone": "0208-990011", "email": "stock@generalgoods.com", "address": "Spintex Road, near Flower Pot, Accra"},
            {"name": "Elite Business Supplies", "phone": "0553-112244", "email": "admin@elitesupplies.com", "address": "Collins Avenue, near Chapel Hill, Takoradi"}
        ]

        customers = []
        for cust_info in customers_data:
            cust = Customer(
                name=cust_info["name"],
                phone=cust_info["phone"],
                email=cust_info["email"],
                address=cust_info["address"]
            )
            db.session.add(cust)
            customers.append(cust)
        db.session.flush()

        # 5. Simulate Sales and Purchases over the past 30 days
        print("Generating transaction history...")
        start_date = datetime.date.today() - datetime.timedelta(days=30)
        
        # Track sold quantities to offset with purchases
        total_sold = {p.id: 0 for p in products}
        sales_records = []

        # We will create about 45 sales transactions
        for i in range(45):
            # Select random date in last 30 days
            days_ago = random.randint(0, 30)
            sale_date = datetime.date.today() - datetime.timedelta(days=days_ago)
            cust = random.choice(customers)
            
            sale = Sale(sale_date=sale_date, customer=cust)
            sales_records.append(sale)
            
            # Select 1 to 4 random products for this sale
            selected_prods = random.sample(products, random.randint(1, 4))
            for p in selected_prods:
                # Wholesale bulk quantity (5 to 30 items)
                qty = random.randint(5, 30)
                total_sold[p.id] += qty
                
                item = SaleItem(
                    sale=sale,
                    product=p,
                    quantity=qty,
                    price_at_sale=p.unit_price
                )
                db.session.add(item)
        
        # Save Sales
        for sale in sales_records:
            db.session.add(sale)
        db.session.flush()

        # Generate Purchases
        # For each product, the total purchased quantity = total_sold + target_ending_stock
        for p in products:
            # Wholesale target ending stock: random buffer above safety levels
            target_stock = p.min_stock_alert + random.randint(10, 50)
            required_purchase_qty = total_sold[p.id] + target_stock
            
            # Split required purchase quantity into 3 transactions distributed over the 30 days
            # This ensures we stock up before sales occur and maintain healthy levels
            dates = [
                datetime.date.today() - datetime.timedelta(days=28), # Initial major restocking
                datetime.date.today() - datetime.timedelta(days=18), # Mid-month top up
                datetime.date.today() - datetime.timedelta(days=8)   # Recent restocking
            ]
            
            # Divide required qty into 3 parts
            qty_parts = [
                int(required_purchase_qty * 0.5),
                int(required_purchase_qty * 0.3),
                required_purchase_qty - int(required_purchase_qty * 0.5) - int(required_purchase_qty * 0.3)
            ]
            
            # Purchase cost is wholesale basis (55% to 70% of retail price)
            cost_factor = Decimal(random.uniform(0.55, 0.70))
            purchase_price = (p.unit_price * cost_factor).quantize(Decimal('0.01'))

            for d, qty in zip(dates, qty_parts):
                if qty <= 0:
                    continue
                purchase = Purchase(
                    product=p,
                    supplier=product_supplier_map[p],
                    quantity=qty,
                    purchase_price=purchase_price,
                    purchase_date=d
                )
                db.session.add(purchase)
            
            # Set the exact ending stock level on the product
            p.quantity_in_stock = target_stock

        db.session.commit()
        print("Database seeded successfully with wholesale records!")

if __name__ == "__main__":
    seed()
