from extensions import db

class Category(db.Model):
    # Unique per business, not globally: one tenant naming a category "Beverages"
    # must not stop every other tenant from doing the same (F-17).
    __table_args__ = (db.UniqueConstraint('business_id', 'name', name='uq_category_business_name'),)

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    products = db.relationship('Product', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

class Supplier(db.Model):
    __table_args__ = (db.UniqueConstraint('business_id', 'name', name='uq_supplier_business_name'),)

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    purchases = db.relationship('Purchase', backref='supplier', lazy=True)

    def __repr__(self):
        return f'<Supplier {self.name}>'

class Brand(db.Model):
    __table_args__ = (db.UniqueConstraint('business_id', 'name', name='uq_brand_business_name'),)

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    products = db.relationship('Product', backref='brand', lazy=True)

    def __repr__(self):
        return f'<Brand {self.name}>'

class ItemGroup(db.Model):
    __table_args__ = (db.UniqueConstraint('business_id', 'name', name='uq_item_group_business_name'),)

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    category = db.relationship('Category', backref='item_groups', lazy=True)
    products = db.relationship('Product', backref='item_group', lazy=True)

    def __repr__(self):
        return f'<ItemGroup {self.name}>'

class Product(db.Model):
    __table_args__ = (db.UniqueConstraint('business_id', 'sku', name='uq_product_business_sku'),)

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    quantity_in_stock = db.Column(db.Integer, nullable=False, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    min_stock_alert = db.Column(db.Integer, nullable=False, default=0)
    
    # Variant & UoM fields
    item_group_id = db.Column(db.Integer, db.ForeignKey('item_group.id'), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'), nullable=False)
    variant_label = db.Column(db.String(100))
    size_value = db.Column(db.Numeric(10, 2))
    size_unit = db.Column(db.String(20))
    barcode = db.Column(db.String(100))
    cost_price = db.Column(db.Numeric(10, 2), nullable=False)
    base_uom = db.Column(db.String(20), nullable=False)
    purchase_uom = db.Column(db.String(20), nullable=False)
    units_per_purchase_uom = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<Product {self.name}>' 