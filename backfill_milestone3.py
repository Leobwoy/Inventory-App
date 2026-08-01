import os
from app import create_app
from extensions import db
from auth.models import Business
from products.models import Product, Brand, ItemGroup, Category
from purchases.models import Purchase, PurchaseOrder, PurchaseOrderItem, StockBatch
from datetime import date

def backfill():
    app = create_app()
    with app.app_context():
        businesses = Business.query.all()
        for business in businesses:
            # 1. Create Default Brand and ItemGroup
            brand = Brand.query.filter_by(business_id=business.id, name='Default Brand').first()
            if not brand:
                brand = Brand(business_id=business.id, name='Default Brand')
                db.session.add(brand)
            
            item_group = ItemGroup.query.filter_by(business_id=business.id, name='Default ItemGroup').first()
            if not item_group:
                item_group = ItemGroup(business_id=business.id, name='Default ItemGroup')
                db.session.add(item_group)
            
            db.session.flush() # So we get the IDs
            
            # 2. Backfill Products
            products = Product.query.filter_by(business_id=business.id).all()
            for product in products:
                if not product.brand_id:
                    product.brand_id = brand.id
                if not product.item_group_id:
                    product.item_group_id = item_group.id
                if not product.cost_price:
                    product.cost_price = product.unit_price
                if not product.base_uom:
                    product.base_uom = 'pcs'
                if not product.purchase_uom:
                    product.purchase_uom = 'pcs'
                if not product.units_per_purchase_uom:
                    product.units_per_purchase_uom = 1
                
                # 3. Create StockBatch if none exists for this product
                existing_batch = StockBatch.query.filter_by(product_id=product.id).first()
                if not existing_batch and product.quantity_in_stock > 0:
                    batch = StockBatch(
                        business_id=business.id,
                        product_id=product.id,
                        batch_number=f"INITIAL-{product.id}",
                        quantity_received=product.quantity_in_stock,
                        quantity_remaining=product.quantity_in_stock,
                        received_date=date.today()
                    )
                    db.session.add(batch)
            
        # 4. Migrate Purchases to PurchaseOrders
        # Note: In Milestone 2, we didn't add business_id to Purchase? Let's check if Purchase has business_id.
        # It should, because we updated it. But wait, we access purchase.product.business_id to be safe.
        purchases = Purchase.query.all()
        for purchase in purchases:
            # Check if already migrated
            # We can use the purchase.id as a reference in some way, but let's just create them.
            # To avoid duplicates, we can check if a PO exists for this purchase.
            # Since this script runs once, we just create them.
            if not purchase.product:
                continue # Edge case
            
            po = PurchaseOrder(
                business_id=purchase.product.business_id,
                supplier_id=purchase.supplier.id if purchase.supplier else None,
                status='received',
                order_date=purchase.purchase_date,
                expected_date=purchase.purchase_date
            )
            db.session.add(po)
            db.session.flush()
            
            poi = PurchaseOrderItem(
                po_id=po.id,
                product_id=purchase.product_id,
                quantity_ordered=purchase.quantity,
                quantity_received=purchase.quantity,
                unit_cost=purchase.purchase_price
            )
            db.session.add(poi)
            
            # Since the stock is already in Product.quantity_in_stock, and we created an INITIAL batch,
            # we don't necessarily need to create a batch for every historic purchase unless we want to split them up.
            # For simplicity, we just leave the StockBatches as the INITIAL ones created above.
            
        db.session.commit()
        print("Backfill completed successfully.")

if __name__ == '__main__':
    backfill()
