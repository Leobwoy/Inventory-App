"""Audit trail.

AuditLog was modelled and migrated with zero writes anywhere in the codebase
(F-19), so there was no way to answer "who changed this price" - the question the
table was designed for. This module is the one place entries are written.

Never raises: an audit failure must not roll back the business operation it is
recording. A missing log line is bad; a lost sale is worse.
"""
import json

from flask_login import current_user

from auth.models import AuditLog
from extensions import db


def log(action, entity_type=None, entity_id=None, business_id=None, user_id=None, **details):
    """Record an audited action. Does not commit - the caller owns the transaction.

    `details` is free-form context stored as JSON: the before/after of a price
    change, the quantity of a stock adjustment, which permissions changed.
    """
    try:
        if business_id is None and getattr(current_user, 'is_authenticated', False):
            business_id = current_user.business_id
        if user_id is None and getattr(current_user, 'is_authenticated', False):
            user_id = current_user.id
        if business_id is None:
            return None

        entry = AuditLog(
            business_id=business_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=json.dumps(details, default=str) if details else None,
        )
        db.session.add(entry)
        return entry
    except Exception:
        # Deliberately swallowed - see module docstring.
        return None


def recent(business_id, limit=200, action=None, entity_type=None):
    """Most recent entries for a business, newest first."""
    query = AuditLog.query.filter_by(business_id=business_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    return query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
