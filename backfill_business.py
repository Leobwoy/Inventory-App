from app import create_app
from extensions import db
from auth.models import Business, Role, Permission, RolePermission
from products.models import Product, Category, Supplier
from sales.models import Customer, Sale
from purchases.models import Purchase

app = create_app()

with app.app_context():
    # 1. Create a default business if none exists
    business = Business.query.first()
    if not business:
        business = Business(name="Default Business")
        db.session.add(business)
        db.session.commit()
        print(f"Created Default Business with ID: {business.id}")
    else:
        print(f"Using existing Business with ID: {business.id}")

    # 2. Backfill business_id in all models
    models_to_update = [Product, Category, Supplier, Customer, Sale, Purchase]
    for model in models_to_update:
        records = model.query.filter_by(business_id=None).all()
        for record in records:
            record.business_id = business.id
        print(f"Backfilled {len(records)} records for {model.__name__}")

    # 3. Seed Roles and Permissions
    roles_data = [
        ("Owner", True),
        ("Manager", True),
        ("Inventory Staff", True),
        ("Sales Staff", True),
        ("Viewer", True)
    ]
    for name, is_sys in roles_data:
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name, is_system_role=is_sys))

    permissions_data = [
        ("products.view", "View products"),
        ("products.create", "Create or edit products"),
        ("products.delete", "Delete products"),
        ("cost_price.view", "View cost price and margin"),
        ("suppliers.manage", "View and manage suppliers"),
        ("purchase_orders.create", "Create purchase orders"),
        ("purchase_orders.approve", "Approve purchase orders"),
        ("goods_receipt.mark", "Mark goods as received"),
        ("sales.create", "Create sales"),
        ("sales.void", "Void or delete sales"),
        ("customers.manage", "View and manage customers"),
        ("reports.view", "View reports"),
        ("reports.export", "Export reports"),
        ("backup.run", "Run backup and restore database"),
        ("users.manage", "Create, edit, revoke, or delete users"),
        ("audit.view", "View audit log")
    ]
    for code, desc in permissions_data:
        if not Permission.query.filter_by(code=code).first():
            db.session.add(Permission(code=code, description=desc))
    
    db.session.commit()
    print("Seed roles and permissions completed.")

    # Apply permission matrix logic
    owner_role = Role.query.filter_by(name="Owner").first()
    manager_role = Role.query.filter_by(name="Manager").first()
    inventory_role = Role.query.filter_by(name="Inventory Staff").first()
    sales_role = Role.query.filter_by(name="Sales Staff").first()
    viewer_role = Role.query.filter_by(name="Viewer").first()

    all_perms = Permission.query.all()
    if owner_role and not owner_role.permissions:
        owner_role.permissions.extend(all_perms)
    
    if manager_role and not manager_role.permissions:
        manager_perms = [p for p in all_perms if p.code not in ("backup.run", "users.manage")]
        manager_role.permissions.extend(manager_perms)

    if inventory_role and not inventory_role.permissions:
        inv_codes = ["products.view", "products.create", "suppliers.manage", "purchase_orders.create", "goods_receipt.mark", "reports.view", "reports.export"]
        inventory_role.permissions.extend([p for p in all_perms if p.code in inv_codes])

    if sales_role and not sales_role.permissions:
        sales_codes = ["products.view", "sales.create", "customers.manage", "reports.view"]
        sales_role.permissions.extend([p for p in all_perms if p.code in sales_codes])

    if viewer_role and not viewer_role.permissions:
        viewer_role.permissions.extend([p for p in all_perms if p.code in ("products.view", "reports.view")])

    db.session.commit()
    print("Permission matrix seeded successfully!")
