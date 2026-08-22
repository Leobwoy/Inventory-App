# -*- coding: utf-8 -*-
"""Make a business camera-ready.

Not seed data - the products and suppliers are already yours. This arranges
what is *showing*, because half a demo's realism is the state of the screens:

* Debts of different sizes at different ages, so the money-owed page has the
  shape of a real book rather than three tidy rows.
* Uneven amounts. Three customers owing exactly 5,000 reads as a test account.
* Nothing on camera called Vody or Test.

Run it against a demo business, never a real one:

    python demo/stage_data.py                    # the local dev database
"""
import datetime
import random
import sys

random.seed(4)
TODAY = datetime.date.today()

#: Roughly how much is still owed, and how many days ago the sale happened.
#: One badly overdue, a couple in the middle, several recent - the spread is
#: the point, not the totals.
DEBTS = [(4280.00, 97), (915.50, 63), (12640.00, 41), (2375.25, 34),
         (688.00, 22), (5140.75, 15), (1290.00, 9), (3465.50, 4)]

JUNK = ('vody', 'test', 'u4', 'sample', 'demo')


def main():
    # The project root, so this runs from anywhere rather than only from it.
    import pathlib

    root = str(pathlib.Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    import app as flask_app

    application = flask_app.create_app()
    with application.app_context():
        from extensions import db
        from auth.models import Business
        from products.models import Product
        from sales.models import Customer, Sale, SaleItem

        business = Business.query.order_by(Business.id).first()
        if business is None:
            raise SystemExit('No business in this database.')
        print('Staging %s' % business.name)

        # 1. Anything that looks like a leftover comes off camera. Deactivated,
        #    never deleted - it keeps its history and can come back.
        hidden = 0
        for product in Product.query.filter_by(business_id=business.id):
            name = (product.name or '').lower()
            if any(word in name.split() or word in name for word in JUNK):
                if product.is_active:
                    product.is_active = False
                    hidden += 1
        print('  hid %d leftover product(s)' % hidden)

        # 2. Enough debtors to fill a screen.
        names = ['Adjei Enterprise', 'Boateng Provisions', 'Mensah & Sons',
                 'Owusu Cold Store', 'Serwaa Mini Mart', 'Nkrumah Drinks Centre',
                 'Tetteh Beverages', 'Ampofo Wholesale']
        customers = []
        for name in names:
            found = Customer.query.filter_by(business_id=business.id, name=name).first()
            if found is None:
                found = Customer(business_id=business.id, name=name,
                                 phone='+233 24 %03d %04d' % (random.randint(100, 999),
                                                              random.randint(1000, 9999)))
                db.session.add(found)
            customers.append(found)
        db.session.flush()

        sellable = (Product.query
                    .filter(Product.business_id == business.id,
                            Product.is_active.isnot(False),
                            Product.quantity_in_stock > 0)
                    .order_by(Product.id).all())
        if not sellable:
            raise SystemExit('Nothing in stock to build a credit sale from.')

        made = 0
        for customer, (owed, days) in zip(customers, DEBTS):
            when = TODAY - datetime.timedelta(days=days)
            if Sale.query.filter_by(business_id=business.id,
                                    customer_id=customer.id,
                                    sale_date=when).first():
                continue
            sale = Sale(business_id=business.id, customer_id=customer.id,
                        sale_date=when)
            db.session.add(sale)
            db.session.flush()
            # One line carrying the whole balance. The page ages and totals the
            # sale; how many lines it took to get there is not on camera.
            product = sellable[made % len(sellable)]
            db.session.add(SaleItem(
                sale_id=sale.id, product_id=product.id, quantity=1,
                price_at_sale=owed, list_price=owed,
                sell_unit='base', sold_quantity=1))
            made += 1
        db.session.commit()
        print('  %d customer(s) now owe money, oldest %d days' % (made, DEBTS[0][1]))
        print('\nReady. Record with:  python demo/record.py')


if __name__ == '__main__':
    sys.exit(main())
