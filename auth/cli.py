import click
from flask.cli import with_appcontext
from extensions import db
from auth.models import User, Business, Role
from werkzeug.security import generate_password_hash


@click.command('reconcile-stock')
@click.option('--fix', is_flag=True, help='Repair the cached quantities instead of only reporting.')
@with_appcontext
def reconcile_stock_command(fix):
    """Report products whose cached stock disagrees with their batch sum.

    Drift means something changed stock outside services/stock.py. A clean run
    is the invariant that module exists to hold.
    """
    from services import stock

    drift = stock.find_drift()
    if not drift:
        click.echo('No drift: every product matches the sum of its batches.')
        return

    click.echo(f'{len(drift)} product(s) out of step:')
    for product, cached, actual in drift:
        click.echo(f'  {product.sku:<20} cached={cached:<8} batches={actual:<8} delta={actual - cached:+}')

    if fix:
        stock.reconcile()
        db.session.commit()
        click.echo(f'\nRepaired {len(drift)} product(s) from their batch sums.')
    else:
        click.echo('\nRe-run with --fix to repair.')

@click.command('create-owner')
@click.argument('email')
@click.argument('password')
@click.argument('name')
@with_appcontext
def create_owner_command(email, password, name):
    business = Business.query.first()
    if not business:
        click.echo("No business found. Please run backfill_business.py first.")
        return
    
    owner_role = Role.query.filter_by(name='Owner').first()
    if not owner_role:
        click.echo("Owner role not found.")
        return
    
    if User.query.filter_by(email=email, business_id=business.id).first():
        click.echo("User with this email already exists.")
        return
        
    user = User(
        business_id=business.id,
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        role_id=owner_role.id
    )
    db.session.add(user)
    db.session.commit()
    click.echo(f"Owner user {email} created successfully!")
