from flask import Flask, render_template
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect
import os
from extensions import db
from flask import send_file, request, redirect, url_for, flash
from flask_migrate import Migrate
from flask_login import LoginManager

# Initialize extensions
bootstrap = Bootstrap()
csrf = CSRFProtect()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'devkey')
    
    db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres123@localhost:5432/purchasesalesdb')
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    bootstrap.init_app(app)
    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        from auth.models import User
        return User.query.get(int(user_id))

    # Register blueprints
    from products.routes import products_bp
    from sales.routes import sales_bp
    from purchases.routes import purchases_bp
    from reports.routes import reports_bp
    from auth.routes import auth_bp
    from auth import models as auth_models
    from products.models import Product
    from billing import models as billing_models
    from sales.models import Sale
    from sqlalchemy import func
    import datetime

    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(purchases_bp, url_prefix='/purchases')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from auth.cli import create_owner_command, reconcile_stock_command
    app.cli.add_command(create_owner_command)
    app.cli.add_command(reconcile_stock_command)

    from flask_login import login_required, current_user
    from auth.decorators import permission_required

    @app.route('/')
    @login_required
    def index():
        from sales.models import SaleItem

        business_id = current_user.business_id
        today = datetime.date.today()
        window_start = today - datetime.timedelta(days=6)

        # Low stock products
        low_stock = Product.query.filter(
            Product.quantity_in_stock <= Product.min_stock_alert,
            Product.business_id == business_id
        ).all()

        # Sales trend, aggregated in SQL. This previously loaded every Sale in the
        # window and lazy-loaded every SaleItem to produce seven numbers (F-14).
        sales_data = {window_start + datetime.timedelta(days=i): 0.0 for i in range(7)}
        rows = (
            db.session.query(
                Sale.sale_date,
                func.sum(SaleItem.price_at_sale * SaleItem.quantity)
            )
            .join(SaleItem, SaleItem.sale_id == Sale.id)
            .filter(Sale.business_id == business_id, Sale.sale_date >= window_start)
            .group_by(Sale.sale_date)
            .all()
        )
        for sale_date, revenue in rows:
            if sale_date in sales_data:
                sales_data[sale_date] = float(revenue or 0)

        # Real product count - this card previously rendered len(top_products),
        # which is capped at 5 by the limit below (F-13).
        product_count = db.session.query(func.count(Product.id)).filter(
            Product.business_id == business_id
        ).scalar() or 0

        # Top 5 products by stock
        top_products = Product.query.filter_by(business_id=business_id).order_by(Product.quantity_in_stock.desc()).limit(5).all()
        return render_template(
            'index.html',
            low_stock=low_stock,
            sales_data=sales_data,
            top_products=top_products,
            product_count=product_count,
            year=today.year,
        )

    @app.route('/backup_restore', methods=['GET', 'POST'])
    @login_required
    @permission_required('backup.run')
    def backup_restore():
        """Export or restore THIS business's data only.

        Scoped per tenant: the export contains just the caller's rows, and the
        import writes only into the caller's business_id, remapping primary keys.
        """
        from services import audit
        from services import backup as backup_service

        if request.method == 'POST':
            if 'backup' in request.form:
                try:
                    archive, filename = backup_service.export_business(current_user.business_id)
                except Exception as e:
                    flash(f'Export failed: {e}', 'danger')
                    return redirect(url_for('backup_restore'))
                audit.log('backup.export', entity_type='business',
                          entity_id=current_user.business_id, filename=filename)
                db.session.commit()
                return send_file(
                    archive,
                    mimetype='application/zip',
                    as_attachment=True,
                    download_name=filename,
                )

            if 'restore' in request.form:
                upload = request.files.get('restore_file')
                if not upload or not upload.filename:
                    flash('Choose a backup file to restore.', 'danger')
                    return redirect(url_for('backup_restore'))
                if request.form.get('confirm_restore') != 'REPLACE':
                    flash('Type REPLACE to confirm - restoring overwrites your current data.', 'warning')
                    return redirect(url_for('backup_restore'))
                try:
                    written = backup_service.import_business(current_user.business_id, upload)
                    audit.log('backup.restore', entity_type='business',
                              entity_id=current_user.business_id,
                              filename=upload.filename, rows=written)
                    db.session.commit()
                except ValueError as e:
                    db.session.rollback()
                    flash(str(e), 'danger')
                    return redirect(url_for('backup_restore'))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Restore failed, no changes were made: {e}', 'danger')
                    return redirect(url_for('backup_restore'))

                total = sum(written.values())
                flash(f'Restored {total} record(s) into {current_user.business.name}.', 'success')
                return redirect(url_for('backup_restore'))

        return render_template('backup_restore.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True) 