from flask import Flask, render_template
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect
import os
from extensions import db
import subprocess
from flask import send_file, request, redirect, url_for, flash
from flask_migrate import Migrate
from flask_httpauth import HTTPBasicAuth
from flask_login import LoginManager

# Initialize extensions
bootstrap = Bootstrap()
csrf = CSRFProtect()
migrate = Migrate()
auth = HTTPBasicAuth()
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

    @auth.verify_password
    def verify_password(username, password):
        expected_password = os.environ.get('BACKUP_PASSWORD', 'admin123')
        if username == 'admin' and password == expected_password:
            return username
        return None

    # Register blueprints
    from products.routes import products_bp
    from sales.routes import sales_bp
    from purchases.routes import purchases_bp
    from reports.routes import reports_bp
    from auth.routes import auth_bp
    from auth import models as auth_models
    from products.models import Product
    from sales.models import Sale
    from sqlalchemy import func
    import datetime

    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(purchases_bp, url_prefix='/purchases')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from auth.cli import create_owner_command
    app.cli.add_command(create_owner_command)

    from flask_login import login_required, current_user

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
    @auth.login_required
    def backup_restore():
        if request.method == 'POST':
            if 'backup' in request.form:
                # Backup: use pg_dump
                backup_file = 'db_backup.sql'
                db_url = app.config['SQLALCHEMY_DATABASE_URI']
                # Parse db_url for credentials using urllib.parse
                from urllib.parse import urlparse
                parsed = urlparse(db_url)
                user = parsed.username
                password = parsed.password
                host = parsed.hostname
                port = str(parsed.port or 5432)
                dbname = parsed.path.lstrip('/')
                if not (user and password and host and dbname):
                    flash('Database URL parsing failed. Check your configuration.', 'danger')
                    return redirect(url_for('backup_restore'))
                env = os.environ.copy()
                env['PGPASSWORD'] = password
                cmd = [
                    'pg_dump',
                    '-h', host,
                    '-p', port,
                    '-U', user,
                    '-F', 'c',
                    '-b',
                    '-v',
                    '-f', backup_file,
                    dbname
                ]
                subprocess.run(cmd, env=env, check=True)
                return send_file(backup_file, as_attachment=True)
            elif 'restore' in request.form:
                # Restore: use psql
                file = request.files['restore_file']
                if not file:
                    flash('No file selected for restore.', 'danger')
                    return redirect(url_for('backup_restore'))
                restore_path = 'restore_upload.sql'
                file.save(restore_path)
                db_url = app.config['SQLALCHEMY_DATABASE_URI']
                # Parse db_url for credentials using urllib.parse
                from urllib.parse import urlparse
                parsed = urlparse(db_url)
                user = parsed.username
                password = parsed.password
                host = parsed.hostname
                port = str(parsed.port or 5432)
                dbname = parsed.path.lstrip('/')
                if not (user and password and host and dbname):
                    flash('Database URL parsing failed. Check your configuration.', 'danger')
                    return redirect(url_for('backup_restore'))
                env = os.environ.copy()
                env['PGPASSWORD'] = password
                # Drop and recreate the database
                drop_cmd = ['psql', '-h', host, '-p', port, '-U', user, '-c', f'DROP DATABASE IF EXISTS {dbname};']
                create_cmd = ['psql', '-h', host, '-p', port, '-U', user, '-c', f'CREATE DATABASE {dbname};']
                subprocess.run(drop_cmd, env=env, check=True)
                subprocess.run(create_cmd, env=env, check=True)
                # Restore
                restore_cmd = [
                    'pg_restore',
                    '-h', host,
                    '-p', port,
                    '-U', user,
                    '-d', dbname,
                    '-v',
                    restore_path
                ]
                subprocess.run(restore_cmd, env=env, check=True)
                flash('Database restored successfully.', 'success')
                return redirect(url_for('backup_restore'))
        return render_template('backup_restore.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True) 