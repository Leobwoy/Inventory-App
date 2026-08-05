from functools import wraps

from flask import abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user


def _wants_json():
    """True for the JSON API.

    Redirecting an API client to a login page hands it HTML to parse as JSON,
    so it cannot tell "signed out" from "not on your plan" from a sale that
    actually failed. Flashing at it is no better: the message surfaces on some
    unrelated page later, with no context.
    """
    return request.blueprint == 'api' or request.path.startswith('/api/')


def _json_error(message, status, code):
    return jsonify({'error': message, 'code': code}), status


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
                if _wants_json():
                    return _json_error('Sign in again.', 401, 'unauthenticated')
                return redirect(url_for('auth.login', next=request.url))

            if not all(current_user.can(code) for code in permission_codes):
                if _wants_json():
                    return _json_error('You do not have permission to do that.',
                                       403, 'forbidden')
                flash("You do not have permission to do that.", "danger")
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requires_feature(feature_code):
    """Require the business's plan to include `feature_code`.

    Distinct from permission_required: that asks whether this person may act,
    this asks whether the business has paid for the capability. A plan ceiling is
    a sales conversation rather than a security event, so this redirects with an
    upgrade prompt instead of returning 403.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if _wants_json():
                    return _json_error('Sign in again.', 401, 'unauthenticated')
                return redirect(url_for('auth.login', next=request.url))

            from billing.plans import FEATURES
            from services.limits import has_feature

            if not has_feature(feature_code):
                description = FEATURES.get(feature_code, (feature_code, None))[0]
                if _wants_json():
                    return _json_error(
                        f'{description} is not included in your current plan.',
                        403, 'feature_locked')
                flash(f'{description} is not included in your current plan.', 'warning')
                return redirect(url_for('index'))

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
                if _wants_json():
                    return _json_error('Sign in again.', 401, 'unauthenticated')
                return redirect(url_for('auth.login', next=request.url))

            if not any(current_user.can(code) for code in permission_codes):
                if _wants_json():
                    return _json_error('You do not have permission to do that.',
                                       403, 'forbidden')
                flash("You do not have permission to do that.", "danger")
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
