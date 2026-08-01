import click
from flask.cli import with_appcontext
from extensions import db
from auth.models import User, Business, Role
from werkzeug.security import generate_password_hash

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
