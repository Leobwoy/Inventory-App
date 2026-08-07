from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class PlatformAdmin(db.Model):
    """Whoever runs TrackTrack. Not a tenant, and not a User.

    There is no registration page. Accounts are created with
    `flask create-platform-admin`, which needs shell access to the server - so
    the set of people who can confirm payments is exactly the set of people who
    can already deploy the application.
    """
    __tablename__ = 'platform_admin'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def __repr__(self):
        return f'<PlatformAdmin {self.email}>'
