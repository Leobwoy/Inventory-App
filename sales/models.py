from decimal import Decimal

from extensions import db

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    sales = db.relationship('Sale', backref='customer', lazy=True)

    def __repr__(self):
        return f'<Customer {self.name}>'

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    sale_date = db.Column(db.Date, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    # Who bought it when they are not in the customer list. Without this a
    # walk-in who buys on credit is anonymous, and the credit book cannot tell
    # one of them from another.
    customer_name = db.Column(db.String(100))
    # A debt you cannot phone is a debt you do not collect.
    customer_phone = db.Column(db.String(50))
    items = db.relationship('SaleItem', backref='sale', lazy=True, cascade='all, delete-orphan')

    @property
    def buyer_name(self):
        """Who to chase for the money, registered customer or walk-in."""
        if self.customer:
            return self.customer.name
        return self.customer_name or 'Walk-in customer'

    @property
    def buyer_phone(self):
        return self.customer.phone if self.customer else self.customer_phone

    @property
    def total_discount(self):
        return sum((item.discount * item.quantity for item in self.items), Decimal('0'))

    @property
    def was_discounted(self):
        return self.total_discount > 0

    def __repr__(self):
        return f'<Sale {self.id}>'

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_at_sale = db.Column(db.Numeric(10, 2), nullable=False)
    # What the product listed for on the day. Kept because product prices move,
    # so a discount cannot be recovered by comparing against today's price.
    list_price = db.Column(db.Numeric(10, 2))
    product = db.relationship('Product')

    @property
    def discount(self):
        """Cedis off the listed price on this line. Zero if there was none."""
        if self.list_price is None:
            return Decimal('0')
        return max(Decimal('0'), self.list_price - self.price_at_sale)

    @property
    def discount_percent(self):
        if not self.list_price:
            return Decimal('0')
        return (self.discount / self.list_price * 100).quantize(Decimal('0.01'))

    @property
    def was_discounted(self):
        return self.discount > 0

    def __repr__(self):
        return f'<SaleItem {self.product.name} x{self.quantity}>'