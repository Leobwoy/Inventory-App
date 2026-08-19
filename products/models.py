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
    # Opt-in, because most of what this market sells does not meaningfully
    # expire. Warning about every carton of mineral water teaches people to
    # ignore warnings, and then the yoghurt goes unread with the rest (D1).
    track_expiry = db.Column(db.Boolean, nullable=False, default=False)
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
    # Six decimals because it is derived, not typed: the form asks what a carton
    # costs and this is that divided by the pack size. At two decimals the edit
    # form's round trip drifts - 1,000 for 24 stores 41.67 and reads back 1,000.08
    # (F-41, and d7e93b04c815 on the selling side).
    cost_price = db.Column(db.Numeric(14, 6), nullable=False)
    base_uom = db.Column(db.String(20), nullable=False)
    purchase_uom = db.Column(db.String(20), nullable=False)
    units_per_purchase_uom = db.Column(db.Integer, nullable=False, default=1)
    # What a whole pack sells for. Nullable, and null is not "free" - it means
    # a pack is simply count x unit_price. A real value is a wholesale price,
    # which cannot be derived: the gap between a bottle at 48 and the same
    # bottle inside a 1,050 carton of 24 is why a shop buys the carton.
    pack_price = db.Column(db.Numeric(10, 2))
    # 'base' | 'purchase' | 'both'. Every product that existed before this
    # column sold in pieces, because that was the only thing the app could do.
    sell_unit = db.Column(db.String(10), nullable=False, default='base',
                          server_default=db.text("'base'"))
    # NOT NULL because plan limits count active products: a NULL would be
    # neither counted nor blocked, which is the gap someone gaming the free tier
    # would find. Deactivating retires a product from new sales and orders while
    # leaving all of its history intact.
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text('true'))
    # Why it is switched off, not just that it is. A product the owner retired
    # and one the plan switched off look identical in `is_active`, and telling a
    # wholesaler that a line they deliberately stopped stocking is "locked by
    # your plan - upgrade to unlock" would be a lie in the one place this app
    # is asking them for money.
    locked_by_plan = db.Column(db.Boolean, nullable=False, default=False,
                               server_default=db.text('false'))

    def __repr__(self):
        return f'<Product {self.name}>' 