from extensions import db
from flask_login import UserMixin
from datetime import datetime

class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_alert_days = db.Column(db.Integer, default=30)
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

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(100))
    entity_id = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    details_json = db.Column(db.Text)
