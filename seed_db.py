"""Seed a realistic Ghanaian beverage/FMCG wholesaler for local development.

The previous seeder was written against the pre-Milestone-3 schema: it built
Product rows with no business_id, brand_id, item_group_id, cost_price or
base_uom (all now NOT NULL) and wrote legacy Purchase rows, so it could not run
at all - while the README told new developers to run it as a setup step (F-10).

This version goes through the real schema: a Business with an Owner and staff,
a brand/item-group catalogue, purchase orders that are actually received into
StockBatch rows, and sales that draw stock down FEFO.

Destructive: rebuilds the database from migrations first.

    python seed_db.py            # prompts before wiping
    python seed_db.py --yes      # no prompt
"""
import datetime
import random
import sys
from decimal import Decimal

from flask_migrate import upgrade
from werkzeug.security import generate_password_hash

from app import create_app
from extensions import db
from auth.models import Business, Role, User
from products.models import Brand, Category, ItemGroup, Product, Supplier
from purchases.models import PurchaseOrder, PurchaseOrderItem, StockBatch
from sales.models import Customer, Sale, SaleItem

random.seed(20260731)  # reproducible datasets

BUSINESS_NAME = 'Accra Beverage Distributors'
OWNER_EMAIL = 'owner@accrabev.com'
DEMO_PASSWORD = 'TrackTrack!23'

CATEGORIES = [
    ('Beverages', 'Water, soft drinks, juices and malt'),
    ('Provisions', 'Shelf-stable household goods'),
]

# item group -> the brands competing within it
ITEM_GROUPS = {
    'Bottled Water': ['BelAqua', 'Verna', 'Voltic'],
    'Soft Drinks': ['Coca-Cola', 'Pepsi'],
    'Malt Drinks': ['Malta Guinness', 'Vitamalt'],
    'Soya Drinks': ['U-Fresh'],
}

# variant label -> (size_value, size_unit, cost, price, units per carton, shelf life in days)
VARIANTS = {
    'Bottled Water': [('500ml', 500, 'ml', '1.20', '2.00', 24, None),
                      ('750ml', 750, 'ml', '1.80', '3.00', 24, None),
                      ('1.5L', 1500, 'ml', '2.60', '4.50', 12, None)],
    'Soft Drinks':   [('350ml', 350, 'ml', '3.20', '5.00', 24, 120),
                      ('1.5L', 1500, 'ml', '7.50', '11.00', 12, 120)],
    'Malt Drinks':   [('330ml', 330, 'ml', '4.80', '7.50', 24, 180)],
    # Short shelf life, so recent receipts land inside the 30-day expiry window
    # and the alert has something real to show.
    'Soya Drinks':   [('500ml', 500, 'ml', '3.50', '5.50', 12, 30)],
}

SUPPLIERS = [
    ('Voltic Ghana Ltd', 'Kwame Asare', '0244112233', 'sales@voltic.com.gh', 'Spintex Road, Accra'),
    ('Accra Bulk Beverages', 'Ama Owusu', '0201445566', 'orders@accrabulk.com', 'Kaneshie Market, Accra'),
    ('Takoradi Drinks Depot', 'Yaw Boateng', '0553778899', 'depot@takoradidrinks.com', 'Market Circle, Takoradi'),
]

CUSTOMERS = [
    ('Madina Provisions', '0244556677', 'madina@shops.gh', 'Madina Market, Accra'),
    ('Kaneshie Superstore', '0208899001', 'kaneshie@shops.gh', 'Kaneshie, Accra'),
    ('Tema Community 1 Store', '0277334455', 'tema@shops.gh', 'Community 1, Tema'),
    ('Kasoa Wholesale Corner', '0501122334', 'kasoa@shops.gh', 'Kasoa New Market'),
    ('Osu Mini Mart', '0243009988', 'osu@shops.gh', 'Oxford Street, Osu'),
]

STAFF = [
    ('Ama Darko', 'ama@accrabev.com', 'Manager'),
    ('Kwesi Appiah', 'kwesi@accrabev.com', 'Inventory Staff'),
    ('Efua Mensah', 'efua@accrabev.com', 'Sales Staff'),
]


def seed(auto_yes=False):
    app = create_app()
    with app.app_context():
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        shown = uri.split('@')[-1] if '@' in uri else uri
        print(f'This DROPS EVERY TABLE in: {shown}')
        if not auto_yes and input('Continue? [y/N] ').strip().lower() not in ('y', 'yes'):
            print('Aborted.')
            return

        print('Rebuilding schema from migrations...')
        db.drop_all()
        db.session.execute(db.text('DROP TABLE IF EXISTS alembic_version'))
        db.session.commit()
        upgrade()  # creates tables AND seeds roles/permissions

        # --- business + users -------------------------------------------------
        business = Business(name=BUSINESS_NAME, address='Spintex Road, Accra',
                            contact_number='0302 555 000', expiry_alert_days=30)
        db.session.add(business)
        db.session.flush()

        roles = {r.name: r for r in Role.query.all()}
        owner = User(business_id=business.id, name='Kofi Mensah', email=OWNER_EMAIL,
                     password_hash=generate_password_hash(DEMO_PASSWORD),
                     role_id=roles['Owner'].id, must_change_password=False)
        db.session.add(owner)
        db.session.flush()
        owner.apply_role_preset('Owner')

        for name, email, role_name in STAFF:
            staff = User(business_id=business.id, name=name, email=email,
                         password_hash=generate_password_hash(DEMO_PASSWORD),
                         role_id=roles[role_name].id, must_change_password=False)
            db.session.add(staff)
            db.session.flush()
            # Roles are only presets - authorization reads UserPermission, so
            # without this the seeded staff would have no permissions at all.
            staff.apply_role_preset(role_name)

        # --- catalogue --------------------------------------------------------
        categories = {}
        for name, desc in CATEGORIES:
            c = Category(business_id=business.id, name=name, description=desc)
            db.session.add(c)
            categories[name] = c
        db.session.flush()

        brands, groups = {}, {}
        for group_name, brand_names in ITEM_GROUPS.items():
            g = ItemGroup(business_id=business.id, name=group_name,
                          category_id=categories['Beverages'].id)
            db.session.add(g)
            groups[group_name] = g
            for b in brand_names:
                if b not in brands:
                    brands[b] = Brand(business_id=business.id, name=b)
                    db.session.add(brands[b])
        db.session.flush()

        products = []
        for group_name, brand_names in ITEM_GROUPS.items():
            for brand_name in brand_names:
                for label, size, unit, cost, price, per_carton, shelf_life in VARIANTS[group_name]:
                    sku = f'{brand_name[:4].upper().replace("-", "")}-{group_name[:4].upper()}-{label.upper()}'
                    p = Product(
                        business_id=business.id,
                        name=f'{brand_name} {label}',
                        sku=sku,
                        description=f'{brand_name} {group_name.lower()}, {label}',
                        category_id=categories['Beverages'].id,
                        item_group_id=groups[group_name].id,
                        brand_id=brands[brand_name].id,
                        variant_label=label,
                        size_value=Decimal(size),
                        size_unit=unit,
                        barcode=f'60{random.randint(10**9, 10**10 - 1)}',
                        cost_price=Decimal(cost),
                        unit_price=Decimal(price),
                        quantity_in_stock=0,          # only goods receipt adds stock
                        min_stock_alert=per_carton,   # one carton is a realistic reorder point
                        base_uom='pcs',
                        purchase_uom='carton',
                        units_per_purchase_uom=per_carton,
                        is_active=True,
                    )
                    p._shelf_life = shelf_life        # transient, used below
                    db.session.add(p)
                    products.append(p)

        suppliers = []
        for name, contact, phone, email, address in SUPPLIERS:
            s = Supplier(business_id=business.id, name=name, contact=contact,
                         phone=phone, email=email, address=address)
            db.session.add(s)
            suppliers.append(s)

        customers = []
        for name, phone, email, address in CUSTOMERS:
            c = Customer(business_id=business.id, name=name, phone=phone,
                         email=email, address=address)
            db.session.add(c)
            customers.append(c)
        db.session.flush()

        # --- purchase orders, received into batches ---------------------------
        today = datetime.date.today()
        po_count = batch_count = 0
        for weeks_ago in range(8, 0, -1):
            order_date = today - datetime.timedelta(days=weeks_ago * 7)
            supplier = random.choice(suppliers)
            po = PurchaseOrder(
                business_id=business.id,
                supplier_id=supplier.id,
                status='ordered',
                order_date=order_date,
                expected_date=order_date + datetime.timedelta(days=random.randint(3, 10)),
            )
            db.session.add(po)
            db.session.flush()
            po_count += 1

            for product in random.sample(products, random.randint(6, 10)):
                cartons = random.randint(15, 40)
                qty = cartons * product.units_per_purchase_uom
                item = PurchaseOrderItem(
                    po_id=po.id, product_id=product.id,
                    quantity_ordered=qty, quantity_received=0,
                    unit_cost=product.cost_price,
                )
                db.session.add(item)
                db.session.flush()

                # The most recent PO stays outstanding so the receive screen has work to do
                if weeks_ago == 1:
                    continue

                received_date = order_date + datetime.timedelta(days=random.randint(2, 8))
                item.quantity_received = qty
                expiry = (received_date + datetime.timedelta(days=product._shelf_life)
                          if product._shelf_life else None)
                db.session.add(StockBatch(
                    business_id=business.id, product_id=product.id, po_item_id=item.id,
                    batch_number=f'PO-{po.id}-{item.id}',
                    quantity_received=qty, quantity_remaining=qty,
                    received_date=received_date, expiry_date=expiry,
                ))
                product.quantity_in_stock += qty
                batch_count += 1
                po.status = 'received'

        db.session.flush()

        # --- sales, drawing stock down FEFO -----------------------------------
        sale_count = item_count = 0
        for days_ago in range(30, -1, -1):
            sale_date = today - datetime.timedelta(days=days_ago)
            for _ in range(random.randint(1, 4)):
                in_stock = [p for p in products if p.quantity_in_stock > 20]
                if not in_stock:
                    continue
                sale = Sale(business_id=business.id, sale_date=sale_date,
                            customer_id=random.choice(customers).id)
                db.session.add(sale)
                db.session.flush()
                sale_count += 1

                for product in random.sample(in_stock, min(len(in_stock), random.randint(1, 4))):
                    qty = min(product.quantity_in_stock,
                              random.randint(1, 4) * product.units_per_purchase_uom)
                    if qty <= 0:
                        continue
                    db.session.add(SaleItem(sale_id=sale.id, product_id=product.id,
                                            quantity=qty, price_at_sale=product.unit_price))
                    product.quantity_in_stock -= qty
                    item_count += 1

                    # FEFO: soonest expiry first, undated batches last
                    remaining = qty
                    batches = StockBatch.query.filter(
                        StockBatch.business_id == business.id,
                        StockBatch.product_id == product.id,
                        StockBatch.quantity_remaining > 0,
                    ).order_by(
                        StockBatch.expiry_date.asc().nulls_last(),
                        StockBatch.received_date.asc(),
                    ).all()
                    for batch in batches:
                        if remaining <= 0:
                            break
                        take = min(batch.quantity_remaining, remaining)
                        batch.quantity_remaining -= take
                        remaining -= take

        db.session.commit()

        low_stock = sum(1 for p in products if p.quantity_in_stock <= p.min_stock_alert)
        expiring = StockBatch.query.filter(
            StockBatch.expiry_date.isnot(None),
            StockBatch.expiry_date <= today + datetime.timedelta(days=30),
            StockBatch.quantity_remaining > 0,
        ).count()

        print(f"""
Seeded {BUSINESS_NAME}
  {len(brands)} brands across {len(groups)} item groups
  {len(products)} product variants
  {len(suppliers)} suppliers, {len(customers)} customers
  {po_count} purchase orders ({batch_count} received into stock batches, 1 left outstanding)
  {sale_count} sales / {item_count} line items over the last 30 days
  {low_stock} products below their reorder threshold
  {expiring} stock batches expiring within 30 days

Log in as:
  Owner            {OWNER_EMAIL}
  Manager          ama@accrabev.com
  Inventory Staff  kwesi@accrabev.com
  Sales Staff      efua@accrabev.com
  Password (all)   {DEMO_PASSWORD}
""")


if __name__ == '__main__':
    seed(auto_yes='--yes' in sys.argv)
