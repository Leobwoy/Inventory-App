# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- **Stage 2 — Differentiation.** Stage 0 and Stage 1 complete. Stage 2.1–2.3 complete.

## Current Goal

- **Stage 2.5 — Notification centre and expiry alerts.** Stage 2.4 is complete (a–d) and
  the app is **deployed and live** at `https://inventory-app-svrn.onrender.com`.

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
  Logo bytes live in the row, not on disk — the host rebuilds the container on every deploy,
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
- **2.4c/2.4d** Offline sale capture and sync. Built together on purpose: a queue that
  cannot sync holds real sales hostage on one device, which is worse than no queue.
  `api/` is the first JSON surface — `/api/v1/session`, `/catalogue`, `/sales`. It **calls
  the same services the forms call**; a second implementation of "how much stock is there"
  would drift, and the drifted copy would be the one running when the shop had no network.
  Three guarantees, each with falsified tests:
  **not lost** — nothing leaves the device queue except the server confirming it, so a
  network error, a bad status and a parse failure all mean retry;
  **not doubled** — the device generates `client_id` before queueing, and `Sale.client_id`
  is unique per business, so a sync that timed out after committing returns the original
  (enforced in the route *and* by the constraint);
  **not quietly wrong** — stock and price are re-decided at sync time, and a conflict is
  kept, shown in red on `/sales/pending`, and left for a person to resolve.
  The catalogue endpoint deliberately omits cost price: the device cache is readable by
  anyone holding the phone, and cost is gated everywhere else (F-16).
  `auth/decorators.py` and the Flask-Login unauthorized handler now answer the API in JSON
  — a 302 to an HTML login page left the device unable to tell an expired session from a
  refused sale, and the safe reading of that is to retry forever.
  `services/limits.has_feature` is memoised per request: templates ask it a dozen times a
  page and each ask was two queries.
- **Review round (F-40).** Fixes from an automated review of the PR, mostly in code from
  this branch. The one that mattered most: **`effective_plan` failed open on a null date** —
  a subscription with `status='active'` and no `paid_through` kept a paid plan forever, and
  the test helper `put_on` created exactly that state, so every billing test sat on the
  fail-open branch and none of them could see it. Missing dates now deny.
  Also: API responses carry `Cache-Control: no-store` (`/session` hands out a CSRF token
  and names the user; `/catalogue` carries customer phone numbers); malformed quantities
  and amounts are **rejected, not retried** — as `retry` they sat in the device queue
  forever, failing identically on every reconnect; audit date filters are parsed, since a
  raw string compared against a timestamp column returns 500 on PostgreSQL for anyone
  holding `audit.view`; the sale form renumbers rows after a removal, or a later add
  reuses an index and the POST binds the wrong product; the offline queue drains a backlog
  larger than one batch; the offline page no longer claims a queued sale is on the server;
  supplier deletion is refused when purchase history depends on it; purchase orders refuse
  inactive products; `products_with_alternatives` went from two queries per product to two
  for the page; label/control associations and the combobox's accessible name.
  **A test of mine asserted the wrong behaviour**: with `uom_conversion` off the template
  hides the unit selector, but the WTForms field still defaults to `'purchase'`, so a
  quantity typed in pieces was multiplied by the conversion factor. The old test posted the
  unit by hand, which hid the real case, and justified it as "the server is the authority".
  Entered values are now base units whenever the business lacks the feature.
  A follow-up round caught that my first fix for undated purchase orders was only half of
  one: `nullslast()` stopped a dateless order becoming a supplier's *latest* price, but a
  supplier whose orders were **all** undated still yielded `last_ordered=None`, which then
  met a real date inside `max()` in `savings_against_latest` and raised `TypeError`.
  `PurchaseOrder.order_date` is nullable, so this was reachable. Undated lines are now
  excluded from the sourcing read entirely — every figure it produces is time-ordered, and
  a line that cannot be placed in time cannot answer any of them — with a null-safe key in
  `savings_against_latest` as defence in depth.
  **F-41 fixed**: `PurchaseOrderItem.unit_cost` widened to `Numeric(14, 6)` and
  `cost_to_base` quantises the *divided* figure to six decimals. Two decimals on a derived
  per-unit cost lost money on every unit of the line — ₵1.00 a carton of 24 recorded ₵96.00
  against ₵100.00 paid over 100 cartons — and that figure is the cost price behind every
  margin and the number `services/sourcing.py` compares suppliers on, so the error landed
  in the one feature meant to answer who is cheaper. A cost typed directly in base units
  stays at 2dp; widening it would invent precision nobody entered. Fixed before first
  deploy deliberately: with no production data the migration is as cheap as it will ever be.
  A third round found three more: `Decimal()` accepts `'NaN'` and `'Infinity'` without
  raising, and `Infinity` was the dangerous one — `min(received, total)` clamped it to the
  full amount, so a malformed payload would have recorded a sale as **paid in full when
  nothing was received**; the batched sourcing query loaded every priced line for the
  business and discarded most in Python, defeating the batching; and the offline queue only
  continued to the next batch when *every* sale was accepted, so one refused sale in fifty
  stranded the other forty-nine. A conflict is terminal — it drops out of the pending
  filter — so the condition is now "every sale reached a terminal state", with `retry` still
  stopping the loop so a sale that cannot go never spins.
- **2.4a** Assets vendored. Bootstrap, Bootstrap Icons and Chart.js served from
  `static/vendor/` with pinned versions; jQuery and Select2 removed in favour of
  `static/js/combobox.js`. No template loads anything from another origin, which is a
  precondition for the service worker in 2.4b.

**332 tests passing**, locally and under bare `pytest` on CI-resolved versions.

## In Progress

- Nothing. Stage 2.4 and the manual mobile money billing flow are committed.

## Next Up

1. **Stage 2.5** — Notification centre and expiry alerts (expiry opt-in per item group)
2. **Stage 2.6** — Supplier scorecards (last: needs 20–30 completed POs to show anything)
3. **Stage 2.7** — Smart reorder
4. **Stage 2.8** — Dashboard rebuild
5. **Stage 2B** — Paystack billing flow
6. **Stage 3** — Interface revamp (light theme, self-hosted assets, barcode sale entry,
   branded invoices)

## Open Questions

- **Promotional discounts do not exist.** Point-of-sale discounting works (a per-line
  price reduction, permission-gated, capped, audited) now that the ceiling is settable.
  What has never been built is a *scheduled* discount attached to goods — "10% off this
  brand until Friday", or a customer price tier. That is a distinct feature: it needs a
  price-rule model, a date window, and a resolution order when rules overlap. Raised by
  the user; not scoped or scheduled yet.
- **Paystack deferred indefinitely (B5).** It needs a registered Ghanaian business and a
  corporate bank account, and registering costs money the project does not have. Switching
  aggregator does not help — Hubtel, ExpressPay, theTeller, Flutterwave and MTN's own API
  all require the same, because Bank of Ghana KYC rules govern merchant settlement rather
  than the companies being awkward.
  **Collection is manual mobile money instead**, and the gap is smaller than it looks:
  mobile money in Ghana has no reusable authorisation, so even a finished Paystack
  integration needs the customer to actively pay again every month. Automation only changes
  *who presses confirm* — worth 1.95% eventually, not worth blocking every customer on a
  company registration today. Register when TrackTrack has paid for it.
  Taking business payments into a personal wallet is a bridge, not a destination: wallets
  have monthly ceilings and mixing business with personal money is unpleasant at tax time.
- **B6 — the vendor console (`platform_console/`).** Confirming a payment decides what a
  business has paid for, so it cannot be a permission: a tenant Owner controls every
  permission inside their own business and would grant it to themselves. The first attempt
  used an email whitelist against the tenant login, which meant running TrackTrack required
  registering a business you do not own — the user pushed back and was right. A platform
  admin now has **its own table, its own login and its own session key**, so a tenant
  session grants nothing there and a console session grants nothing here. No signup page:
  accounts come from `flask create-platform-admin`, so whoever can confirm payments is
  exactly whoever can already deploy. `flask confirm-payment` is the fallback when the
  browser is not an option. Console covers payments, a customer list, and changing a plan
  by hand (comping, corrections) — every change audited into the affected business's own
  log, so the business can see it too.
- **Deployed 2026-08-05** to Render + Neon (Frankfurt). `DEPLOY.md` has the walkthrough.
  Production config:
  `SECRET_KEY` is now **required** in production (it silently fell back to a default
  written in this repository, which anyone reading the code could use to forge a session),
  secure cookie flags are set, `ProxyFix` handles Render's TLS termination, and the engine
  pre-pings because Neon drops idle connections.
- **Free-tier retention.** What happens to a business sitting on Kiosk for two years with
  500 deactivated products? A retention question, tied to the Ghana Data Protection Act
  review in Stage 4.
- **GRA / VAT e-invoicing** is legally required for VAT-registered wholesalers but sits in
  Stage 4. Revisit before pilot.
- **Roadmap Phase 3 contradiction.** "Supplier ad placements" undermines the unbiased
  price comparison that Stage 2.3 just built. Unresolved; you can have one or the other.
- **Deployment host changed.** Koyeb was acquired by Mistral and new signups land on a
  marketing page with no way to create a service. **Render** replaces it. The original
  objection to Render — its free Postgres self-deletes after 30 days — does not apply,
  because the database is Neon and Render only runs the container. Free instance sleeps
  after 15 min (~1 min cold start); $7/month removes it. See `DEPLOY.md`.
- **Dependency pinning.** Now bounded (floor excludes the Werkzeug CVEs, ceiling stops an
  unannounced major). Exact pins with a lockfile remain the right end state.
- **Free-tier cold start.** Both Neon and Render idle out; the first request after a quiet
  spell takes up to a minute on Render. Fine for a demo you warn people about, and the first thing worth
  paying to remove before real pilot users. See `DEPLOY.md`.

## Architecture Decisions

| # | Decision | Why |
| --- | --- | --- |
| D1 | Target customer is beverage/FMCG wholesale | Expiry/FEFO drops to secondary and opt-in per item group; brand comparison, UoM and credit become the differentiators |
| D2 | Credit ledger moved from roadmap Phase 2 into Phase 1 | Ghanaian wholesale runs on trade credit; "who owes me what" outranks supplier analytics |
| D3 | Offline is a Phase 1 requirement | Absent from the original roadmap; patchy connectivity and metered data are the defining market constraints |
| D4 | No Viewer role; authorization is per user | `UserPermission` is the single source of truth, roles are presets the Owner then edits per person |
| D5 | Render + Neon, Frankfurt | Koyeb was the original choice and was acquired by Mistral, leaving no way to create a service. Render's *free Postgres* self-deletes after 30 days, which is why it lost first time — irrelevant now, because Neon holds the data and Render only runs the container. AWS has no free Postgres or persistent server and new accounts close after 6 months |
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
