from flask import Flask, render_template
from flask_bootstrap import Bootstrap
from flask_wtf.csrf import CSRFProtect
import os
from extensions import db
import subprocess
from flask import send_file, request, redirect, url_for, flash

# Initialize extensions
bootstrap = Bootstrap()
csrf = CSRFProtect()

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

    # Register blueprints
    from products.routes import products_bp
    from sales.routes import sales_bp
    from purchases.routes import purchases_bp
    from reports.routes import reports_bp
    from products.models import Product
    from sales.models import Sale
    from sqlalchemy import func
    import datetime

    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(purchases_bp, url_prefix='/purchases')
    app.register_blueprint(reports_bp, url_prefix='/reports')

    @app.route('/')
    def index():
        # Low stock products
        low_stock = Product.query.filter(Product.quantity_in_stock <= Product.min_stock_alert).all()
        # Sales trend (last 7 days) for multi-item sales
        today = datetime.date.today()
        sales_dates = [(today - datetime.timedelta(days=i)) for i in range(6, -1, -1)]
        sales_data = {d: 0.0 for d in sales_dates}
        sales = Sale.query.filter(Sale.sale_date >= today - datetime.timedelta(days=6)).all()
        for sale in sales:
            day = sale.sale_date
            for item in sale.items:
                if day in sales_data:
                    sales_data[day] += float(item.price_at_sale) * item.quantity
        # Top 5 products by stock
        top_products = Product.query.order_by(Product.quantity_in_stock.desc()).limit(5).all()
        return render_template('index.html', low_stock=low_stock, sales_data=sales_data, top_products=top_products, year=datetime.date.today().year)

    @app.route('/backup_restore', methods=['GET', 'POST'])
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