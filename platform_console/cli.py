"""Console commands.

The console has no signup page, on purpose: the set of people who can confirm
payments should be exactly the set of people who can already deploy the
application. Creating an account therefore needs shell access.

confirm-payment is the fallback the console is not - a way through when the
browser is not an option, or when something in the web layer is broken and the
money still has to be settled today.
"""
import click
from flask.cli import with_appcontext

from extensions import db


@click.command('create-platform-admin')
@click.option('--email', prompt=True, help='Sign-in address for the console.')
@click.option('--name', prompt=True, help='Shown in the console header.')
@click.password_option(help='Chosen interactively; never passed on the command line.')
@with_appcontext
def create_platform_admin_command(email, name, password):
    """Create a console account for whoever runs TrackTrack."""
    from platform_console.models import PlatformAdmin

    email = email.strip().lower()
    if PlatformAdmin.query.filter_by(email=email).first():
        raise click.ClickException(f'{email} already has a console account.')
    if len(password) < 12:
        # Longer than the tenant minimum: this account can change what every
        # business has paid for.
        raise click.ClickException('Use at least 12 characters for a console password.')

    admin = PlatformAdmin(email=email, name=name.strip())
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo(f'Console account created for {email}. Sign in at /platform/login')


@click.command('list-platform-admins')
@with_appcontext
def list_platform_admins_command():
    """Who can currently reach the console."""
    from platform_console.models import PlatformAdmin

    admins = PlatformAdmin.query.order_by(PlatformAdmin.id).all()
    if not admins:
        click.echo('No console accounts. Create one with create-platform-admin.')
        return
    for admin in admins:
        state = '' if admin.is_active else '  (deactivated)'
        seen = admin.last_login_at.strftime('%d %b %Y') if admin.last_login_at else 'never'
        click.echo(f'{admin.email:<40} {admin.name:<25} last seen {seen}{state}')


@click.command('pending-payments')
@with_appcontext
def pending_payments_command():
    """Claimed payments waiting to be checked."""
    from auth.models import Business
    from services import billing as billing_service

    pending = billing_service.pending_payments()
    if not pending:
        click.echo('Nothing waiting.')
        return
    for transaction in pending:
        business = db.session.get(Business, transaction.business_id)
        click.echo(f'{transaction.provider_ref:<30} '
                   f'{(business.name if business else "?"):<30} '
                   f'GHS {transaction.amount_ghs}  '
                   f'{transaction.created_at:%d %b %H:%M}')


@click.command('confirm-payment')
@click.argument('reference')
@click.option('--by', default='cli', help='Recorded in the audit trail.')
@click.option('--note', default=None)
@with_appcontext
def confirm_payment_command(reference, by, note):
    """Confirm a claimed payment by its transaction ID.

    The same service the console calls, so the two cannot drift into treating
    the same payment differently.
    """
    from billing.models import PaymentTransaction
    from services import billing as billing_service

    transaction = PaymentTransaction.query.filter_by(provider_ref=reference.strip()).first()
    if transaction is None:
        raise click.ClickException(f'No payment claimed with reference {reference!r}.')
    if transaction.status != 'pending':
        raise click.ClickException(
            f'That payment is already {transaction.status}; nothing to do.')

    click.echo(f'GHS {transaction.amount_ghs} for '
               f'{transaction.plan.name if transaction.plan else "an unrecorded plan"}')
    click.confirm('Confirm this payment arrived?', abort=True)

    billing_service.confirm(transaction, confirmed_by=by, note=note)
    db.session.commit()
    click.echo('Confirmed. The plan is active.')
