# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- **Stage 2 — Differentiation.** Stage 0 and Stage 1 complete. Stage 2.1–2.3 complete.

## Current Goal

- **Stage 2.4 — PWA and offline sales.** See the approved plan for the full unit
  breakdown. Sub-units in order: 2.4a self-host assets, 2.4b installable shell,
  2.4c offline sale capture, 2.4d sync and conflict handling.

## Completed

### Stage 0 — Unblock and rehost (7 commits, merged)
The app was unusable and undeployable. Three critical defects:
- **F-01** A newly registered business could not create a single product. `brand_id` and
  `item_group_id` are `NOT NULL`, neither was seeded, and all four templates for creating
  them were missing with no navigation. Fixed: templates written, catalogue nav added,
  `Generic` / `Uncategorized` seeded at registration, product form relaxed (SKU
  auto-generates, units default).
- **F-02** Neither deploy path worked. `build.sh` ran `db.create_all()` so migrations
  never ran and roles were never seeded; `flask db upgrade` failed because the chain had
  no baseline. Fixed with migration `0000_baseline` and `flask db upgrade` in `build.sh`.
- **F-03** `/backup_restore` was HTTP Basic auth with `admin`/`admin123`, dumped every
  tenant into one file, and its restore ran `DROP DATABASE`. Replaced with a permission-
  gated per-tenant CSV export and a scoped import that remaps primary keys.

Also fixed: F-04 purchases report queried a dead table; F-08 sales report row totals
always printed 0.00 (Jinja `{% set %}` loop scoping); F-09 three role vocabularies;
F-13/F-14 dashboard; F-20 `/tmp` path; F-21 missing Excel export; F-25 login hardening;
**F-28** every bulk action and list-page delete returned 400 (no CSRF token in six
templates); **F-29** `email_validator` undeclared; **F-30** `PurchaseOrder` had no
`supplier` relationship; **F-31** open redirect on login.

### Stage 1 — Make the foundation real (merged)
- **1.1 (F-05)** IAM authorization. 7 coarse permissions enforced on 2 of 55 routes →
  26 permissions enforced everywhere. `UserPermission` is the authority; `Role` is a
  preset. Per-person permission grid.
- **1.2 (F-16)** Cost price gated at route, form and export level.
- **1.3 (F-06)** Goods receipt rebuilt: per-line quantity, batch, expiry, partial receipt.
  This is what made FEFO and expiry tracking real — every batch previously had a null
  expiry, so FEFO silently degraded to FIFO.
- **1.4 (F-12, F-11)** `services/stock.py` — single source of truth, row locking,
  `flask reconcile-stock`.
- **1.5 (F-07)** Server-side price authority with discount ceiling.
- **1.6 (F-17)** Per-tenant uniqueness; `User.email` reverted to global (see decisions).
- **1.7 (F-19)** Audit log turned on — 16 call sites, Activity page, indexes.
- **1.8 (F-22)** pytest suite + GitHub Actions CI.
- **1.9 (B4)** Billing scaffolding — plans, subscriptions, `services/limits.py`.
- **1.10 (F-15, F-26)** Eager loading and money precision, with query-count tests.
- Plan limits count **active** products and users, not total rows (see decisions).

### Stage 2 — Differentiation (in progress, branch `stage-1-finish`)
- **2.1** Unit-of-measure conversion. Buy in cartons, stock and sell in singles.
  Everything stored in base units; the purchase unit exists only at the edges.
- **2.2** Customer credit book. Sales marked paid / part-paid / on credit; payments with
  mobile money references; ageing buckets; printable statements. Balances derived.
- **2.3** Multi-supplier price comparison. Pure read over purchase history — latest,
  best-ever, average, trend, and what switching would save.

- **2.2 fix (F-32)** The statement's sale rows never showed their own settlement, and
  payment rows did not name the sale they cleared. Paying a sale in full left its row
  looking untouched — `paid` on a sale row is structurally always zero, since the money
  arrives as a separate row sorted by its own date, often pages away. Users read that as
  the payment having failed. Sale rows now carry `settled`/`outstanding`/`status`,
  computed within the as-of window so a back-dated statement is not credited with money
  that had not arrived; payment rows carry `sale_id`. Found by the user testing the demo.
- **2.2 fix (F-34)** Walk-in customers were a dead end in the credit book. The name typed
  on the sale form was never stored — it rode to the invoice as a URL query parameter and
  was gone on reload — and the ageing report groups by customer, so every walk-in
  collapsed into one anonymous, unclickable row with no way to open or settle it.
  `Sale.customer_name` now persists it, and `/credit/walk-ins` lists the debts one sale at
  a time, each with a Record payment button. For a walk-in the unit is the sale, not the
  person: there is no customer record to hold a running balance.
- **F-33 Business Settings.** `/auth/settings`, gated on `settings.manage` — a permission
  that was already in the catalogue and seeded, but which no route had ever used. Business
  name, address, contact, logo, expiry alert window and the discount ceiling. This is what
  makes the Stage 1.5 discount system reachable: `max_discount_percent` defaults to 0, so
  until now discounting was finished, tested code that no business could switch on.
  Logo bytes live in the row, not on disk — Koyeb rebuilds the container on every deploy,
  and there is no object store. `logo_path` dropped; nothing ever wrote to it.
- **F-35 Discounts are visible, not just enforced.** `SaleItem.list_price` records what the
  product listed for on the day, so a discount survives later repricing — it cannot be
  recomputed by comparing an old sale against today's price without inventing discounts
  that never happened. The sale form shows the reduction per line and a total as it is
  typed, and warns before the ceiling is breached rather than after the server refuses it.
  The invoice shows the struck-through list price and the total given.
- **F-36 Invoice carries the business's identity.** It printed "TrackTrack" and our logo
  regardless of whose business it was. Now the business name, address and contact, with
  their logo when uploaded and ours as fallback. A small "Made by TrackTrack" credit stays
  at the foot regardless of branding.
- **F-37 Walk-in phone; payment notes readable.** `Sale.customer_phone` — a debt you cannot
  phone is a debt you do not collect. Payment notes were captured by the form and never
  displayed again; they now appear on the statement.
- **F-38 Corrupted currency symbol.** `templates/sales/add.html` was re-encoded through
  PowerShell's ANSI default during 2.4a, turning every `₵` into `â‚µ`. Repaired, with a
  test asserting the sign renders. **Never round-trip a file through `Get-Content` /
  `Set-Content`** — use `[System.IO.File]::ReadAllText/WriteAllText`, which are UTF-8.
- **F-39 Search, sort and filter on every record list.** Sales had a bulk-action dropdown
  and pagination but no way to find anything — 60 sales a day fills fifteen pages in a
  week. Products had a search box, the audit log had filters, nothing else had either.
  `services/listing.py` plus `templates/_partials/list_toolbar.html` give one shared
  pattern, now on Sales, Products, Purchase Orders, Customers and Suppliers.
  Sort keys are **whitelisted** — a key from the query string is user input and an
  unrecognised one becomes the default rather than reaching the database. State lives
  entirely in the URL, so a filtered list can be bookmarked or shared, and paging keeps
  it. Counts report matches, not page length. Brands, categories, item groups and staff
  are deliberately left alone: they are bounded lists that fit on one screen.
- **2.4b** Installable shell. `manifest.json`, generated icon set (including maskable, or
  Android crops the mark), `static/sw.js`, and an offline fallback page.
  The worker is served from **`/sw.js`, not `/static/sw.js`** — a worker only controls URLs
  beneath its own path, so from `/static` it would see no page of the app.
  **Pages are never cached.** Every page is behind a login and full of one business's
  money; caching would leave those figures on the device after logout, readable on a
  shared phone, and returning hours stale as though current. Static assets are cache-first
  (public, identical for everyone, unchanged until deploy) — only possible because 2.4a
  moved them off the CDN. Non-GET and cross-origin requests are ignored entirely.
  `templates/offline.html` deliberately does **not** extend `base.html`: that template
  branches on whether there is a session, and the first version rendered a full sidebar
  and no content at all for a logged-in reader — which is the case that actually happens.
- **2.4a** Assets vendored. Bootstrap, Bootstrap Icons and Chart.js served from
  `static/vendor/` with pinned versions; jQuery and Select2 removed in favour of
  `static/js/combobox.js`. No template loads anything from another origin, which is a
  precondition for the service worker in 2.4b.

**284 tests passing**, locally and under bare `pytest` on CI-resolved versions.

## In Progress

- **Stage 2.4c** — offline sale capture: cache the catalogue in IndexedDB, queue a sale
  recorded without a signal, show it as unmistakably pending. Then 2.4d syncs it via a new
  `/api/v1/sales` that reuses `services/stock.py` and `services/pricing.py` rather than
  duplicating the rules, returning per-sale accept/conflict.

## Next Up

1. **Stage 2.4** — PWA and offline (current goal above)
2. **Stage 2.5** — Notification centre and expiry alerts (expiry opt-in per item group)
3. **Stage 2.6** — Supplier scorecards (last: needs 20–30 completed POs to show anything)
4. **Stage 2.7** — Smart reorder
5. **Stage 2.8** — Dashboard rebuild
6. **Stage 2B** — Paystack billing flow
7. **Stage 3** — Interface revamp (light theme, self-hosted assets, barcode sale entry,
   branded invoices)

## Open Questions

- **Promotional discounts do not exist.** Point-of-sale discounting works (a per-line
  price reduction, permission-gated, capped, audited) now that the ceiling is settable.
  What has never been built is a *scheduled* discount attached to goods — "10% off this
  brand until Friday", or a customer price tier. That is a distinct feature: it needs a
  price-rule model, a date window, and a resolution order when rules overlap. Raised by
  the user; not scoped or scheduled yet.
- **Paystack merchant registration.** Requires a registered Ghanaian business and a
  corporate bank account. Long lead time; gates Stage 2B regardless of code readiness.
- **Deployment.** Neon + Koyeb accounts not yet provisioned — blocked on the user.
  A PWA needs HTTPS to install, so this blocks verifying Stage 2.4b on a real phone.
- **Free-tier retention.** What happens to a business sitting on Kiosk for two years with
  500 deactivated products? A retention question, tied to the Ghana Data Protection Act
  review in Stage 4.
- **GRA / VAT e-invoicing** is legally required for VAT-registered wholesalers but sits in
  Stage 4. Revisit before pilot.
- **Roadmap Phase 3 contradiction.** "Supplier ad placements" undermines the unbiased
  price comparison that Stage 2.3 just built. Unresolved; you can have one or the other.
- **Dependency pinning.** `requirements.txt` is all `>=`, so Koyeb resolves Flask 3.1.3 /
  pandas 3.0.5 while local development runs older versions. Not currently breaking; pin
  before the pilot.

## Architecture Decisions

| # | Decision | Why |
| --- | --- | --- |
| D1 | Target customer is beverage/FMCG wholesale | Expiry/FEFO drops to secondary and opt-in per item group; brand comparison, UoM and credit become the differentiators |
| D2 | Credit ledger moved from roadmap Phase 2 into Phase 1 | Ghanaian wholesale runs on trade credit; "who owes me what" outranks supplier analytics |
| D3 | Offline is a Phase 1 requirement | Absent from the original roadmap; patchy connectivity and metered data are the defining market constraints |
| D4 | No Viewer role; authorization is per user | `UserPermission` is the single source of truth, roles are presets the Owner then edits per person |
| D5 | Koyeb + Neon, Frankfurt | Free with no expiry clock. Render's free Postgres self-deletes after 30 days. AWS has no free Postgres or persistent server and new accounts close after 6 months |
| D6 | Supplier scorecards sequenced last | They need 20–30 completed POs before they display anything |
| D7 | Onboarding friction is a first-class problem | 12+ required fields per product is the most likely cause of real-world abandonment |
| — | `User.email` is **globally** unique | Built per-tenant first, then reverted. An email must identify a *person*, or every recovery flow inherits the ambiguity — and with shared family or `info@` addresses, a reset scoped to an email hands one person another's credentials. If multi-business users become real, the answer is a `Membership` table or tenant-slug login, not per-tenant emails |
| — | Row-level `business_id`, not schema-per-tenant | Schema-per-tenant means migrations run once per tenant with custom tooling, platform billing queries need schema iteration, and catalog overhead strains the free tier. Row-level scoping is already implemented and audited |
| — | Plan limits count **active** rows | Counting every row let a customer buy one month of a large plan, bulk-load a catalogue, drop to free and keep trading on all of it — and punished honest customers who retired old lines |
| — | Downgrade removes access, never data | Products deactivate, staff suspend, nothing is destroyed. Deleting a wholesaler's catalogue because they stopped paying loses them permanently |
| — | Export works on every plan including free | Never hold a customer's own records hostage. Also a Data Protection Act concern |
| B1 | Paystack behind a provider interface, Hubtel later | Hubtel bundles SMS, which reaches this market better than email for renewal reminders |
| B2 | Meter on users + SKUs + features, never transactions | A wholesaler doing 200 sales/day would breach any sane cap; throttling the busiest customer is the worst possible failure |
| B3 | 14-day full trial → auto-downgrade to permanent free tier | No card required to start; at expiry the account downgrades rather than locking |
| B4 | Billing scaffolded in Stage 1, payment flow in Stage 2B | Metering hooks land while all routes are being touched anyway |
| — | **PWA, not Capacitor** | The service worker *is* the offline mechanism — Capacitor without one still fails offline. PWA is free, ships instantly, and Capacitor remains purely additive later. Revisit if pilot users cannot self-install |
| — | Plan names use the trade ladder | Kiosk / Shop / Depot / Distributor / Enterprise. A customer places themselves on it without reading a feature list. Display only — `Plan.code` is what the app keys off |

## Session Notes

- **Repository**: `Leobwoy/Inventory-App`. Work happens on a branch, then a PR to `main`.
  CodeRabbit reviews automatically; its docstring-coverage and PR-title checks are not
  code defects and can be left failing.
- **Local database**: PostgreSQL on `localhost:5432`, user `postgres` / `postgres123`.
  `python seed_db.py --yes` builds a realistic Accra beverage wholesaler — 16 variants,
  8 POs, ~70 sales, a populated credit book, and multi-supplier price spreads.
  Demo logins are printed at the end; password `TrackTrack!23`.
- **CI runs bare `pytest`**, which resolves `sys.path` differently from `python -m pytest`.
  `pythonpath = .` in `pytest.ini` handles it. Always check both.
- **Three tautological assertions** shipped in this project before being caught — asserting
  against a value derived from the same query as the actual. Falsify tests before trusting
  them.
- **The original strategy document** is `ghana-wholesaler-roadmap.md`. It remains useful
  but these context files supersede it where they disagree; the divergences are recorded
  in the decisions table above.
- **The full audit** (31 findings with severity, locations and a scorecard) exists as an
  HTML report in a scratchpad and was never published. Its content is reflected here.
