# Code Standards

## General

- Business logic lives in `services/`. Routes parse input, call a service, and render.
  If a route contains arithmetic or a rule, it is in the wrong place.
- Fix root causes. Do not layer a guard over a bug that should not be reachable.
- Comments explain **why**, not what. `# loop over items` is noise;
  `# InputRequired, not DataRequired: DataRequired treats 0 as missing` is the reason
  the next person does not undo it.
- Match the density and idiom of the surrounding file.

## Python

- Import order: stdlib, third-party, then local. Absolute imports throughout.
- Import inside a function only to break a genuine circular import, and say so.
- Prefer explicit tuples over booleans for outcomes:
  `can_add_product()` returns `(allowed, message)`, not just `False`.
- Raise domain exceptions (`InsufficientStock`, `PriceRejected`, `PlanLimitReached`)
  and let the route decide presentation.
- Never expose a raw exception to a user. Log with `current_app.logger.exception()`
  and flash a fixed message. Domain exceptions carrying deliberate user-facing text
  are the exception.

## Flask

- One blueprint per domain, registered in `create_app()`.
- Decorator order is `@route`, `@login_required`, `@permission_required`,
  `@requires_feature`, then the function.
- Routes serving several privilege levels (the `bulk_action` endpoints) check per action
  inside the view instead.
- Services never commit. The caller owns the transaction, so a failure part-way rolls the
  whole operation back.
- `db.session.flush()` when an id is needed before commit.

## Forms

- `InputRequired`, not `DataRequired`, for numeric fields. `DataRequired` treats `0` as
  missing, which makes a zero price or a zero stock threshold impossible to save.
- Required means genuinely required. Everything else defaults — a 12-field product form
  is the most likely cause of real-world abandonment.
- Never trust a posted foreign key. Resolve it scoped to the business
  (see `_scoped_catalogue()` in `products/routes.py`).

## Templates

- Every `<form method="post">` carries `{{ form.hidden_tag() }}` or an explicit
  `csrf_token` input. There are no exceptions.
- Jinja has **no `loop.parent`**. Capture an outer index with
  `{% set group_index = loop.index %}` — referencing `loop.parent` raises `UndefinedError`
  and took down a whole page unnoticed.
- A plain `{% set %}` inside a `{% for %}` is scoped to the iteration. Use
  `namespace()` for running totals, or the total silently renders zero.
- Gate on `current_user.can()` and `has_feature()`. Hiding is cosmetic; the route enforces.
- **`content` and `auth_content` are not interchangeable.** `base.html` emits `content` for
  signed-in users and `auth_content` for signed-out ones. A `@login_required` page that
  defines only `auth_content` renders a shell with nothing in it — no error, no clue. This
  has shipped twice: `offline.html` in 2.4b and the change-password gate in F-46, where a
  new employee was told to set a password on a page with no form. A signed-in page that
  wants the centred layout passes `standalone=True` and keeps `auth_content`.

## Migrations

- One migration per logical change, with a docstring saying **why**, not just what.
- Seed and preset data is **inlined** in the migration, never imported from application
  code. A migration is a fixed point in history; importing live constants makes old
  migrations change behaviour when today's code is edited.
- Adding a `NOT NULL` column to a populated table is three steps: add nullable, backfill,
  then enforce.
- Write a working `downgrade()`.
- Guard destructive or re-runnable operations (`IF EXISTS`, `ON CONFLICT DO NOTHING`).

## Data

- Quantities are stored in **base units**, always. The purchase unit exists only at the
  input and display boundaries (`services/uom.py`).
- Money is `Numeric(10, 2)` and `Decimal` in Python. A **derived** per-unit figure may take
  more scale — `PurchaseOrderItem.unit_cost` is `Numeric(14, 6)`, because it comes from
  dividing a line cost by a pack quantity and two decimals lose real money over a carton of
  24. Anything a human types or reads stays at two.
- `Decimal` accepts `'NaN'` and `'Infinity'` without complaint. Any Decimal built from
  outside input is checked with `.is_finite()` before use: NaN poisons every comparison
  downstream, and Infinity sails through a discount floor as the highest price ever charged.
- Nullable columns that gate behaviour are a bug. `Product.is_active` was nullable while
  nothing read it; the moment it gated revenue, a `NULL` row was neither counted nor
  blocked.
- Add indexes with the query they serve, not after the first slow report.

## Tests

- Real PostgreSQL, schema built by `flask db upgrade`. A broken migration chain must fail
  the suite.
- **Verify a test can fail.** Break the code deliberately and confirm the test goes red.
  Three assertions in this project passed while being incapable of failing.
- Never assert against a value derived from the same query as the actual — filtering by
  `business_id` and then asserting every row has that `business_id` proves nothing.
- Test names are sentences: `test_deleting_a_sale_keeps_cache_and_batches_in_step`.
- Docstrings say what would break in production if the test failed.

## File Organization

- `auth/`, `products/`, `sales/`, `purchases/`, `credit/`, `billing/`, `reports/` —
  each holds `models.py`, `forms.py`, `routes.py` for its domain
- `api/` — JSON only, `/api/v1/*`. Never renders a template; never a second copy of a rule
- `platform_console/` — the vendor's console. Imports from tenant domains, never the
  reverse: nothing in the product may depend on the console existing
- `services/` — business logic, no Flask request context assumptions where avoidable
- `templates/<domain>/` — mirrors the blueprint layout
- `migrations/versions/` — the schema's history
- `tests/` — one module per concern, fixtures in `conftest.py`
- `context/` — these files. Keep them current.
