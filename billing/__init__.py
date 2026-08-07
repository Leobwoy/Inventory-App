"""Subscriptions and plan limits.

Deliberately separate from the domain modules: what a business is allowed to do
(billing) is a different question from who is allowed to do it (permissions), and
conflating them makes both harder to reason about.

Payments go through billing/providers.py, which exists so that "did the money
arrive?" is the only thing that varies between a human reading a mobile money
statement and a signed Paystack webhook. Everything after that answer is shared.
"""
from flask import Blueprint

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

from . import routes  # noqa: E402,F401
