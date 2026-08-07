"""Session handling for the console.

Plain session keys rather than Flask-Login, and that is the point. Flask-Login
holds one identity per request, and reusing it would mean a tenant Owner and a
platform admin were the same kind of thing to the framework. They are not, and
the day that distinction blurs is the day a customer confirms their own payment.

Nothing here reads `current_user`, and nothing in `auth/` reads this key.
"""
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

SESSION_KEY = 'platform_admin_id'


def sign_in(admin):
    session[SESSION_KEY] = admin.id
    session.permanent = False


def sign_out():
    session.pop(SESSION_KEY, None)


def current_admin():
    """The signed-in platform admin, or None. Cached per request."""
    if 'platform_admin' in g:
        return g.platform_admin

    admin_id = session.get(SESSION_KEY)
    g.platform_admin = None
    if admin_id:
        from platform_console.models import PlatformAdmin
        admin = PlatformAdmin.query.get(admin_id)
        # Re-checked every request: deactivating an admin has to take effect
        # immediately, not whenever their session happens to expire.
        if admin and admin.is_active:
            g.platform_admin = admin
    return g.platform_admin


def platform_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_admin() is None:
            # The console is not advertised. An unauthenticated request to a
            # console page gets the login form, not a 403 announcing that a
            # console exists and someone else may use it.
            if request.method != 'GET':
                abort(404)
            return redirect(url_for('platform.login'))
        return view(*args, **kwargs)
    return wrapped
