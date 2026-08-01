from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user


def permission_required(*permission_codes):
    """Require every listed permission.

    Reads UserPermission via User.can(), never Role - roles are only presets
    applied at user creation, so authorization has one source of truth and no
    precedence rules. Owners implicitly hold everything.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))

            if not all(current_user.can(code) for code in permission_codes):
                flash("You do not have permission to do that.", "danger")
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def any_permission_required(*permission_codes):
    """Require at least one of the listed permissions.

    For pages that serve several audiences - a list a viewer can read and an
    editor can act on - where the finer-grained check happens inside the view.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))

            if not any(current_user.can(code) for code in permission_codes):
                flash("You do not have permission to do that.", "danger")
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
