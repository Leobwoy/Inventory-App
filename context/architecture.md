# Architecture Context

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Framework | Flask 3.x (Python 3.12) | Application factory in `app.py`, blueprints per domain |
| Templating | Jinja2 + Bootstrap 5.3 (vendored) | Server-rendered HTML; no SPA |
| ORM | SQLAlchemy 2.x + Flask-SQLAlchemy 3.x | Models and queries |
| Migrations | Alembic via Flask-Migrate | **The only way schema changes** |
| Database | PostgreSQL 16 | All persistent state |
| Auth | Flask-Login + `werkzeug.security` | Sessions and password hashing |
| Forms | Flask-WTF / WTForms | Validation and CSRF |
| Reports | ReportLab, pandas, openpyxl, XlsxWriter | PDF / Excel / CSV export |
| Hosting | Render (app) + Neon (Postgres), Frankfurt | Free tier, no expiry clock |
| Server | Gunicorn, via the repo `Dockerfile` | Runs `flask db upgrade` on start |
| Tests | pytest against real PostgreSQL | 665 tests; migrations, not `create_all()` |
| Scheduling | GitHub Actions cron to an HTTP endpoint | No worker process; see Subscription Lifecycle |

Frankfurt is chosen over US or Cape Town regions because West African undersea cables
route north to Europe, so Ghana reaches Frankfurt faster than Johannesburg.

Koyeb was the original host and is gone - it was acquired and stopped letting new
services be created. Render replaced it. Because Neon holds the data, the host is
interchangeable; that was the point of keeping them separate.

`flask_bootstrap` is still initialised in `create_app()` but **no template extends its
base**, and its Bootstrap 3.3.7 assets are never served. The markup is Bootstrap 5.3 from
`static/vendor/`. The extension is dead weight kept only because removing it touches
`create_app()`; it is not a second UI framework.

## System Boundaries

- `auth/` — `Business`, `User`, `Role`, `Permission`, `UserPermission`, `AuditLog`;
  login, registration, staff management, the permission grid, the activity log
- `products/` — `Product`, `Category`, `Brand`, `ItemGroup`, `Supplier`; catalogue CRUD,
  Excel upload, SKU generation
- `purchases/` — `PurchaseOrder`, `PurchaseOrderItem`, `StockBatch`; ordering, goods
  receipt, price comparison pages
- `sales/` — `Sale`, `SaleItem`, `Customer`; recording sales, invoices
- `credit/` — `Payment`; the credit book, ageing, statements
- `billing/` — `Plan`, `Subscription`, `PaymentTransaction`, the plan catalogue, and
  `providers.py` (the `PaymentProvider` interface, currently `ManualMomoProvider`). Also
  hosts the `before_app_request` hook that reconciles a subscription once a day.
- `api/` — JSON endpoints under `/api/v1/*`. Exists for the offline queue and the
  subscription cron. Calls the same services the web forms call; a second implementation of
  "how much stock is there" would drift within weeks, and the copy that drifted would be
  the one running when the shop had no network.
- `platform_console/` — **the vendor's own console, not a tenant feature.** Separate
  `PlatformAdmin` table, session key and decorator. See Two Identity Systems below.
- `reports/` — read-only reporting and export
- `services/` — **all business logic**. Routes stay thin and call in here.
  `stock`, `pricing`, `uom`, `credit`, `sourcing`, `limits`, `audit`, `backup`,
  `billing`, `listing`, `notifications`, `subscriptions`
- `migrations/versions/` — the schema's entire history
- `tests/` — pytest suite, real database, fixtures in `conftest.py`

Blueprints must not import each other's route modules. Cross-domain work goes through
`services/`.

## Storage Model

- **PostgreSQL** holds everything persistent. There is no file store, cache or queue.
- **Session** holds the Flask-Login user id, `platform_admin_id` for a signed-in console
  admin, and `subscription_checked` (a date string throttling the lazy reconcile). Nothing
  else — no entitlement, permission or business id is ever cached there, so a plan or
  permission change takes effect on the next request rather than the next login.
- **Client-side** — IndexedDB holds a cached catalogue and a queue of sales recorded
  offline. It is a staging area, never a source of truth: the server re-validates stock and
  price on sync, against the truth *now* rather than the truth the device had.
- Money is `Numeric(10, 2)`, and the exceptions all follow one rule: **money a human types
  or reads stays at two decimals; money the app derives by dividing keeps six.**
  `Business.max_discount_percent` is `Numeric(5, 2)` — a percentage, not money.
  `PurchaseOrderItem.unit_cost` (F-41), `SaleItem.price_at_sale` and `SaleItem.list_price`
  (Stage U2) and `Product.cost_price` (Stage W2) are all `Numeric(14, 6)`, because each is a
  per-single figure obtained by dividing a pack figure. At two decimals that rounding is real
  money across a carton of 24, and on `cost_price` it also drifts on every edit: 1,000 for 24
  stores 41.67, which the form reads back as a carton costing 1,000.08.
  `Product.unit_price` deliberately stays at two. It is a genuine per-bottle selling price,
  charged in whole pesewas, and it is re-derived from the stored pack price on every save
  rather than round-tripped through the form, so it cannot drift.
- Quantities are integers in **base units**, on every side. Buying converts at the edge
  (`services/uom.to_base`) and, since Stage U, so does selling: a sale line carries the unit
  it was typed in and is converted before `services/stock.py` sees it. Nothing downstream of
  that ever asks which unit a number is in.
- **The pack is the price.** `Product.pack_price` is what the business types and what the
  business quotes; `Product.unit_price` and `Product.cost_price` are per base unit and are
  *derived on save* by dividing the typed pack figures (Stage W2). This inverted in W2 and
  the direction matters: a wholesaler buys, sells and quotes by the carton, and what one
  bottle costs is both a figure they never work out and one no two shops agree on.

  The per-single columns stay stored and stay `NOT NULL`. Deriving rather than dropping them
  is what keeps the change contained — making them nullable would push a NULL into price
  sorting (`products/routes.py` `PRODUCT_SORTS`, where it orders unpredictably on Postgres),
  into the offline catalogue payload, and into every report that multiplies by them.

  A stored pack price is a negotiated wholesale price - a carton of 24 at ₵1,050 is ₵43.75 a
  bottle against ₵48 singly - and no arithmetic on a single price can produce that gap, which
  is why it is the number that is typed rather than the number that is computed.
  `pack_price` is still nullable and null still means "count × unit_price" to
  `services/uom.price_for`, for rows that predate W2; the form no longer creates one.
  A product with no real pack - loose goods - is priced by the single, and both the form and
  `uom.sell_units()` fall back to that. `Product.sell_unit` (`base` | `purchase` | `both`)
  says what may be chosen.
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
   *request*. `readonly` in a template is a rendering hint, never a control (F-07). A posted
   *unit* is gated three times over, in this order: does the plan include `uom_conversion`,
   does the product have a real conversion, and is the unit one `uom.sell_units()` offers.
   Hiding a selector is not enforcing anything - a hand-posted unit must not buy a
   conversion the plan does not include.

14. **Conversion guards live in `services/uom.py`, not in its callers.** `to_base` and
    `cost_to_base` check `has_conversion` themselves. They multiplied on the pack count
    alone until Stage U, and were safe only because both call sites happened to guard
    first; safety that lives in the callers lasts until the third caller.

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

10. **Every POST form carries a CSRF token.** `CSRFProtect` is global and a missing token
    is a silent 400 (F-28). There is exactly **one** exemption,
    `api.cron_subscriptions`: server-to-server, authenticated by a shared secret compared
    with `hmac.compare_digest`, taking no input and idempotent. A scheduler has no
    session and cannot fetch a token first. A Paystack webhook would be the second,
    verified by signature. A third needs all four of those properties, not just the first.

11. **Entitlement is decided on read, never by a scheduled job.**
    `services/limits.effective_plan()` works out what a business may do from the dates on
    the subscription row, on every request. `services/subscriptions.py` only makes the
    stored `status` agree with it. A run that is skipped, late or failed cannot grant a
    paid feature or lock out someone who paid - which matters, because the app runs on an
    instance that sleeps and GitHub's scheduler drops runs when it is busy. If the two
    ever disagree, `effective_plan` is right.

12. **A downgrade rewrites `plan_id`, not just `status`.** `effective_plan` reads
    `status == 'free'` as "on the plan named here, with no expiry" - that is how a comped
    account works. Flipping the status while leaving a paid `plan_id` in place grants that
    plan permanently and it never expires again: the exact opposite of a downgrade.

13. **An alert is only shown to someone allowed to see what it is about.** The alerts
    page spans modules by design, so it crosses permission gates its own `products.view`
    does not cover. `notifications.ALERT_PERMISSIONS` holds the exceptions, and both the
    page and the badge count go through `for_user()` - a badge counting what the page
    then withholds is its own bug.

## Interface Architecture

Server-rendered Jinja with a small number of hand-written components. There is no build
step and no framework - every asset is vendored under `static/`, and
`tests/test_assets.py` fails the build if a CDN link reappears.

- **Theme.** `User.theme_pref` (`system` | `light` | `dark`) plus a blocking pre-paint script
  in `base.html` that resolves `system` from `prefers-color-scheme` before anything renders.
  `<html>` always carries a concrete `data-theme` *and* `data-bs-theme`: Bootstrap 5.3 scopes
  its variables as `:root,[data-bs-theme=light]` and ships no `prefers-color-scheme` support,
  so a missing attribute is not neutral - it is Bootstrap's light theme. Colours are tokens
  in `static/css/style.css`; nothing may hardcode one.
- **The product picker** (`static/js/picker.js`, `templates/_partials/product_picker.html`)
  is the only way a product is chosen. It is the app's **first and only Bootstrap modal** -
  the JS bundle was already loaded and precached on every page, so it cost nothing new. The
  `<select>` stays in the DOM, keeps its name and stays the source of truth; the dialog
  writes to it and fires a bubbling `change`. It is hidden by script, never by the server, so
  a browser running no JavaScript still has a working page.
- **Canvas ignores CSS.** Chart.js reads palette tokens through `getComputedStyle` at build
  time and redraws on `tracktrack:theme` and a `MutationObserver` on `data-theme`.
- **`design/verify/`** renders every page server-side in both themes and measures composited
  contrast in a browser. It is not shipped; it is how "does this page read" stops being an
  opinion. Paned and dialog states get their own captures, because a sweep only measures what
  is visible and says nothing when that is less than it was.

## Two Identity Systems

There are two kinds of person here and they share nothing.

| | Tenant user | Platform admin |
| --- | --- | --- |
| Table | `User` | `PlatformAdmin` |
| Belongs to a business | Always; `business_id` is `NOT NULL` | Never |
| Session key | Flask-Login's `_user_id` | `platform_admin_id` |
| Gate | `@login_required` + `@permission_required` | `@platform_required` |
| Reaches | Their own business's data | Every tenant's billing state |

Separate because both alternatives were worse. Making the vendor a `User` of a placeholder
business would have made `User.business_id` nullable, which holes invariant 1: every scoped
query would need a null case, on every route, forever. And an Owner already holds every
permission inside their business, so anything expressed as a permission would be
self-grantable by the very people it is meant to exclude.

The console is not reachable from the app and has no signup page - the first account is
made from a shell, because the set of people who can confirm payments should be exactly the
set who can already deploy. `@platform_required` returns 404 on POST rather than
redirecting, so a probe cannot confirm the console exists.

## Subscription Lifecycle

Three transitions in `services/subscriptions.py`: `trialing` to `free` when the trial ends,
`active` to `grace` when the paid period lapses, `grace` to `free` after `GRACE_DAYS`. An
`active` row whose grace has *already* elapsed goes straight to `free`, because
`effective_plan` treats active and grace alike - a row that lapsed months ago has no grace
left to enter.

Grace exists because mobile money cannot renew on its own. A lapse means "they have not
paid *yet today*", not "they left".

It runs three ways, none of them authoritative (invariant 11):

- **Lazily**, `before_app_request`, throttled to once a day per signed-in user through the
  session. The marker is written *after* the work, so a connection that blinks is retried
  on the next page rather than written off until tomorrow.
- **On a schedule**, `POST /api/v1/cron/subscriptions`, guarded by `CRON_SECRET`, 404 when
  unset. Called by `.github/workflows/subscriptions.yml` daily. This is what catches the
  businesses that are *not* logging in - the ones worth chasing.
- **By hand**, `flask subscriptions-reconcile [--dry-run]`.

No worker process and no in-app scheduler, deliberately: a background thread on an instance
that sleeps stops when the instance does, and would be the last thing to notice.

## Billing Collection

`billing/providers.py` defines `PaymentProvider` so that "did the money arrive?" is the only
thing differing between a human reading a mobile money statement and a signed webhook.
Everything after that answer - the plan change, the audit entry, the locking - is shared.

`ManualMomoProvider` is the only implementation. A customer sends mobile money and submits
the reference; a platform admin confirms it in the console or by CLI. Both `confirm` and
`reject` take a row lock and re-check `status == 'pending'` *after* acquiring it, so two
admins acting at once cannot both apply.

It works this way because Paystack required a business registration the project could not
fund, and because mobile money has no reusable authorisation - there is no recurring charge
to automate, so a human confirming a renewal costs far less here than it would in a card
market. See Open Questions in `progress-tracker.md`: Paystack access has since changed.
