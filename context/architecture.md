# Architecture Context

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Framework | Flask 3.x (Python 3.12) | Application factory in `app.py`, blueprints per domain |
| Templating | Jinja2 + Flask-Bootstrap 3.3.7 | Server-rendered HTML; no SPA |
| ORM | SQLAlchemy 2.x + Flask-SQLAlchemy 3.x | Models and queries |
| Migrations | Alembic via Flask-Migrate | **The only way schema changes** |
| Database | PostgreSQL 16 | All persistent state |
| Auth | Flask-Login + `werkzeug.security` | Sessions and password hashing |
| Forms | Flask-WTF / WTForms | Validation and CSRF |
| Reports | ReportLab, pandas, openpyxl, XlsxWriter | PDF / Excel / CSV export |
| Hosting | Koyeb (app) + Neon (Postgres), Frankfurt | Free tier, no expiry clock |
| Server | Gunicorn, via the repo `Dockerfile` | Runs `flask db upgrade` on start |
| Tests | pytest against real PostgreSQL | 237 tests; migrations, not `create_all()` |

Frankfurt is chosen over US or Cape Town regions because West African undersea cables
route north to Europe, so Ghana reaches Frankfurt faster than Johannesburg.

## System Boundaries

- `auth/` — `Business`, `User`, `Role`, `Permission`, `UserPermission`, `AuditLog`;
  login, registration, staff management, the permission grid, the activity log
- `products/` — `Product`, `Category`, `Brand`, `ItemGroup`, `Supplier`; catalogue CRUD,
  Excel upload, SKU generation
- `purchases/` — `PurchaseOrder`, `PurchaseOrderItem`, `StockBatch`; ordering, goods
  receipt, price comparison pages
- `sales/` — `Sale`, `SaleItem`, `Customer`; recording sales, invoices
- `credit/` — `Payment`; the credit book, ageing, statements
- `billing/` — `Plan`, `Subscription`, `PaymentTransaction`, and the plan catalogue
- `reports/` — read-only reporting and export
- `services/` — **all business logic**. Routes stay thin and call in here.
  `stock`, `pricing`, `uom`, `credit`, `sourcing`, `limits`, `audit`, `backup`
- `migrations/versions/` — the schema's entire history
- `tests/` — pytest suite, real database, fixtures in `conftest.py`

Blueprints must not import each other's route modules. Cross-domain work goes through
`services/`.

## Storage Model

- **PostgreSQL** holds everything persistent. There is no file store, cache or queue.
- **Session** holds only the Flask-Login user id.
- **Client-side (Stage 2.4)** — IndexedDB will hold a cached catalogue and a queue of
  sales recorded offline. It is a staging area, never a source of truth: the server
  re-validates stock and price on sync.
- Money is `Numeric(10, 2)`. Quantities are integers in **base units**.
- Free-form context on audit entries and payment payloads is JSON in a `Text` column.

## Auth and Access Model

Two independent gates run on nearly every route. Conflating them is the most common
mistake in this codebase.

| Gate | Question | Mechanism |
| --- | --- | --- |
| Permission | May **this person** do it? | `@permission_required('code')` → `User.can()` → `UserPermission` |
| Feature | Has **this business** paid for it? | `@requires_feature('code')` → `services/limits.has_feature()` → `Plan` |

Both must pass. Neither implies the other: a Sales Staff member on the Distributor plan
still cannot manage users; an Owner on Kiosk still cannot open purchasing.

- Identity is global: `User.email` is unique across all tenants, because an email must
  identify a *person* — every recovery flow (password reset, MFA, support) depends on it.
- Everything else is per-tenant: `Product.sku`, `Category.name`, `Supplier.name`,
  `Brand.name`, `ItemGroup.name` are `UniqueConstraint(business_id, ...)`.
- `UserPermission` is the authority. `Role` is a **preset** copied in at user creation,
  never consulted at runtime. Owners implicitly hold every permission.
- A permission failure is `403`. A **plan limit is not** — it is a sales conversation, so
  it flashes an upgrade prompt and re-renders.

## Invariants

Rules the codebase must never violate. Each was learned from a real defect.

1. **Every query is scoped by `business_id`.** Object lookups use
   `filter_by(id=..., business_id=...).first_or_404()`, so tampering with an id in a URL
   returns 404 rather than another tenant's record. Never `get_or_404()`.

2. **Stock changes only through `services/stock.py`.** `StockBatch.quantity_remaining` is
   authoritative; `Product.quantity_in_stock` is a cache that module maintains. Writing
   either directly is how the two silently diverged before (F-12).

3. **The server decides prices and unit conversions.** A posted price or unit is a
   *request*. `readonly` in a template is a rendering hint, never a control (F-07).

4. **Money is `Decimal` end to end.** `float()` only at an export boundary, never before
   a sum.

5. **Schema changes only through migrations.** Never `db.create_all()` — it builds tables
   but runs no seed data, which is exactly how deploys silently produced an app with no
   roles (F-02).

6. **Balances are derived, never stored.** Credit balances compute from sales minus
   payments on every read. A stored balance is a cache, and an unreconciled cache drifts.

7. **Audit writes never raise.** A failed log line must not roll back the operation it
   describes. A missing log entry is bad; a lost sale is worse.

8. **Read-then-write on shared rows takes a row lock.** `deduct_fefo`, `restore`,
   `receive` and goods receipt all use `with_for_update()`. Without it, two tills selling
   the same product both pass the stock check and both write from a stale read.

9. **Customer data is never deleted to enforce a plan limit.** Downgrading removes
   *access*, not records: products deactivate, staff suspend, nothing is destroyed.

10. **Every POST form carries a CSRF token.** `CSRFProtect` is global with no exemptions,
    so a missing token is a silent 400 (F-28). The only future exception will be the
    Paystack webhook, which is server-to-server and verified by signature instead.
