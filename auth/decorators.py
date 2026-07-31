from functools import wraps
from flask import abort, flash, redirect, url_for, request
from flask_login import current_user

def permission_required(permission_code):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.url))
            
            # Check if user's role has the required permission
            if not current_user.role:
                abort(403)
                
            has_permission = any(p.code == permission_code for p in current_user.role.permissions)
            
            if not has_permission:
                flash("You do not have permission to access this page.", "danger")
                abort(403)
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
