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
    __table_args__ = (
        db.UniqueConstraint('business_id', 'client_id', name='uq_sale_business_client_id'),
    )

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
    # The id the device gave this sale before it could send it. Retrying a sync
    # is normal - a timeout after the server committed looks identical to a
    # failure - so the id is what stops the same crate being sold twice.
    client_id = db.Column(db.String(64), index=True)
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
    # Base units, always - two cartons of 24 store 48. Everything that sums
    # `price_at_sale * quantity` keeps working without knowing units exist.
    quantity = db.Column(db.Integer, nullable=False)
    # Per base unit, and six decimals because it is *derived* when a pack is
    # sold: a carton at 1,000 for 24 is 41.666... a bottle, and at two decimals
    # 48 bottles bill 2,000.16 against the 2,000.00 agreed (the F-41 reasoning,
    # on the side the customer pays).
    price_at_sale = db.Column(db.Numeric(14, 6), nullable=False)
    # What the product listed for on the day. Kept because product prices move,
    # so a discount cannot be recovered by comparing against today's price.
    list_price = db.Column(db.Numeric(14, 6))
    # What was actually chosen at the till, kept so the invoice can say "2
    # cartons" rather than "48 bottles". Frozen for the same reason list_price
    # is: a pack size can be corrected later, and deriving `quantity / factor`
    # at read time would silently rewrite an old sale.
    sell_unit = db.Column(db.String(10), nullable=False, default='base',
                          server_default=db.text("'base'"))
    sold_quantity = db.Column(db.Integer)
    product = db.relationship('Product')

    @property
    def sold_as(self):
        """(how many, what they were called) as the customer was billed."""
        from services import uom
        if self.sell_unit == uom.PURCHASE and self.sold_quantity:
            return self.sold_quantity, uom.unit_label(self.product, uom.PURCHASE)
        return self.quantity, uom.unit_label(self.product, uom.BASE)

    @property
    def price_per_sold_unit(self):
        """What one of what they bought cost, for the invoice."""
        from decimal import Decimal, ROUND_HALF_UP
        sold, _label = self.sold_as
        if not sold:
            return Decimal('0.00')
        total = Decimal(str(self.price_at_sale)) * Decimal(self.quantity)
        return (total / Decimal(sold)).quantize(Decimal('0.01'),
                                                rounding=ROUND_HALF_UP)

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