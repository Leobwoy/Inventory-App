from extensions import db
from flask_login import UserMixin
from datetime import datetime

class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_alert_days = db.Column(db.Integer, default=30)
    # Ceiling on how far below list a sale may go, for staff holding
    # sales.discount. Default 0 - discounting is off until an Owner allows it.
    max_discount_percent = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    address = db.Column(db.String(255))
    contact_number = db.Column(db.String(50))
    logo_path = db.Column(db.String(255))
    
    users = db.relationship('User', backref='business', lazy=True)

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    is_system_role = db.Column(db.Boolean, default=True)
    
    users = db.relationship('User', backref='role', lazy=True)
    permissions = db.relationship('Permission', secondary='role_permission', backref=db.backref('roles', lazy='dynamic'))

class Permission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))

class RolePermission(db.Model):
    __tablename__ = 'role_permission'
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    permission_id = db.Column(db.Integer, db.ForeignKey('permission.id'), primary_key=True)

class UserPermission(db.Model):
    """The single source of truth for what a user may do.

    Roles are presets: picking one at user creation copies its permissions in
    here, after which the Owner edits them per person. Authorization never reads
    Role, so there are no precedence rules to reason about when debugging why
    someone can or cannot do something.
    """
    __tablename__ = 'user_permission'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    permission_id = db.Column(db.Integer, db.ForeignKey('permission.id', ondelete='CASCADE'), primary_key=True)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(UserMixin, db.Model):
    # Globally unique, deliberately - unlike the other tenant-scoped tables. An
    # email must identify a *person*, because every identity-recovery flow
    # (password reset, MFA, security alerts, support lookups) depends on that.
    # If one person ever needs accounts at two businesses, the answer is a
    # Membership table, not a per-tenant email.
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, default=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    permissions = db.relationship(
        'Permission',
        secondary='user_permission',
        backref=db.backref('users', lazy='dynamic'),
        lazy='joined',           # loaded with the user; can() is called on every request
    )

    # Owner is the account that registered the business. It always holds every
    # permission, so revoking one by accident can never lock a business out of
    # its own data.
    OWNER_ROLE = 'Owner'

    @property
    def is_owner(self):
        return bool(self.role and self.role.name == self.OWNER_ROLE)

    def can(self, permission_code):
        """True if this user holds `permission_code`. Owners hold everything."""
        if not self.is_active:
            return False
        if self.is_owner:
            return True
        return any(p.code == permission_code for p in self.permissions)

    def permission_codes(self):
        return {p.code for p in self.permissions}

    def set_permissions(self, codes):
        """Replace this user's permissions with exactly `codes`."""
        codes = list(codes)
        self.permissions = Permission.query.filter(Permission.code.in_(codes)).all() if codes else []

    def apply_role_preset(self, role_name):
        """Seed permissions from a role preset. Presets are a starting point only."""
        from auth.permissions import preset_for
        self.set_permissions(preset_for(role_name))

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(100))
    entity_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details_json = db.Column(db.Text)
