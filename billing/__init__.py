"""Subscriptions and plan limits.

Deliberately separate from the domain modules: what a business is allowed to do
(billing) is a different question from who is allowed to do it (permissions), and
conflating them makes both harder to reason about.

No payment provider code lives here yet - see Stage 2B. The models and limit
checks land first so metering hooks exist before there are routes to retrofit.
"""
