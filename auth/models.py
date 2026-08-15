from extensions import db
from flask_login import UserMixin
from datetime import datetime

class Business(db.Model):
    # A ceiling above 100 would make the discount floor negative, silently
    # disabling the limit it exists to enforce.
    __table_args__ = (
        db.CheckConstraint('max_discount_percent >= 0 AND max_discount_percent <= 100',
                           name='ck_business_max_discount_percent_range'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_alert_days = db.Column(db.Integer, default=30)
    # Ceiling on how far below list a sale may go, for staff holding
    # sales.discount. Default 0 - discounting is off until an Owner allows it.
    max_discount_percent = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    address = db.Column(db.String(255))
    contact_number = db.Column(db.String(50))
    # In the row, not on disk: the container is rebuilt on every deploy, so a
    # logo written to the filesystem disappears at the next release.
    logo_data = db.Column(db.LargeBinary)
    logo_mimetype = db.Column(db.String(50))

    users = db.relationship('User', backref='business', lazy=True)

    @property
    def has_logo(self):
        return self.logo_data is not None

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
    # Null means the guided tour has never been finished or dismissed. On the
    # user rather than in localStorage: the question is whether this *person*
    # has been shown the app, not whether this browser has.
    tour_seen_at = db.Column(db.DateTime)

    # 'system' | 'light' | 'dark'. Same reasoning as tour_seen_at - it belongs
    # to the person, not the browser, so the shop tablet and their own phone
    # agree. And not to the business: the owner at a desk and the clerk in a
    # market doorway want opposite things, and only one of them could win.
    #
    # 'system' is stored as itself rather than resolved to a colour. Saving the
    # resolved value would freeze whatever the device said on the day they
    # registered and never follow it again.
    theme_pref = db.Column(db.String(8), nullable=False, server_default='system')

    #: What the server renders before the browser has had a say. 'system'
    #: resolves to dark here and is corrected in the page head - so with
    #: JavaScript off you get exactly the app that existed before this feature.
    THEMES = ('system', 'light', 'dark')

    @property
    def resolved_theme(self):
        return self.theme_pref if self.theme_pref in ('light', 'dark') else 'dark'

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
    # Nullable so an entry survives the user being deleted - the trail must
    # outlive the account, otherwise removing someone erases what they did.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref=db.backref('audit_entries', lazy='dynamic'))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(100))
    entity_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details_json = db.Column(db.Text)
