from extensions import db

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    purchase_price = db.Column(db.Numeric(10, 2), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    purchase_date = db.Column(db.Date, nullable=False)

    product = db.relationship('Product', backref=db.backref('purchases', lazy=True))

    def __repr__(self):
        return f'<Purchase {self.id}>'

class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    status = db.Column(db.String(50), default='draft') # draft, ordered, partially_received, received, cancelled
    order_date = db.Column(db.Date)
    expected_date = db.Column(db.Date)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    approved_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Without this, po.supplier resolves to Undefined in Jinja (silently rendering
    # "N/A" on the PO list) and raises AttributeError in the CSV export. Only the
    # legacy Purchase model had a supplier relationship.
    supplier = db.relationship('Supplier', backref=db.backref('purchase_orders', lazy=True))

    items = db.relationship('PurchaseOrderItem', backref='purchase_order', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<PurchaseOrder {self.id} {self.status}>'

class PurchaseOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity_ordered = db.Column(db.Integer, nullable=False)
    quantity_received = db.Column(db.Integer, default=0)
    # Six decimals, not two: this is a *derived* per-unit figure (a carton price
    # divided by its pack factor), and rounding it to pesewas loses money on
    # every unit of the line. Displayed at two decimals everywhere (F-41).
    unit_cost = db.Column(db.Numeric(14, 6))
    
    product = db.relationship('Product')

class StockBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    po_item_id = db.Column(db.Integer, db.ForeignKey('purchase_order_item.id'), nullable=True)
    batch_number = db.Column(db.String(100))
    quantity_received = db.Column(db.Integer, nullable=False)
    quantity_remaining = db.Column(db.Integer, nullable=False)
    received_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date, nullable=True)

    product = db.relationship('Product', backref=db.backref('batches', lazy=True)) 