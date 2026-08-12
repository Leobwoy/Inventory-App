# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- **Stage 2 — Differentiation.** Stage 0 and Stage 1 complete. Stage 2.1–2.5 complete.

## Current Goal

- **Stage 2.6 — Supplier scorecards.** Stage 2.5 (notifications) and the subscription
  lifecycle are complete. The app is **deployed and live** at
  `https://inventory-app-svrn.onrender.com`.

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
- **2.5 Notification centre and expiry alerts.** `services/notifications.py` plus
  `/products/alerts` — out of stock, below reorder level, expiring, already expired,
  customers overdue past 60 days, and a trial or plan about to lapse. Worst first.
  **Derived, never stored.** Every alert is a fact about the current state, so it is
  computed on read and leaves when the fact stops being true. There is deliberately no
  read/unread: a stored alert can be dismissed while the thing it warns about is still
  happening, and then the screen says all is well with the stock still at zero. The cost is
  that it cannot describe the past — that would be an events table and a different feature.
  **Expiry alerting is opt-in per item group (D1).** `ItemGroup.track_expiry`, default off.
  This market sells mostly things that do not meaningfully expire, and warning about all of
  it is how people learn to ignore warnings. The `?stock=expiring` product filter honours
  the same flag, so the page an alert links to shows what the alert counted.
  The service returns an **endpoint and params, not a built URL**, so it needs no request
  context and stays usable from a CLI command or the SMS reminders that will want the same
  list. The sidebar badge is **fetched after load** rather than rendered: computing it costs
  several queries and the sidebar is on all fifty-odd routes.
  Found while building it: `Subscription.days_left` used `timedelta.days`, which truncates,
  so a 14-day trial read "13 days left" from the moment it started. Now `days_until()`,
  rounding up — part of a day is a day you still have. The existing test tolerated
  `TRIAL_DAYS - 1`, which was accommodating the bug.
- **2.4a** Assets vendored. Bootstrap, Bootstrap Icons and Chart.js served from
  `static/vendor/` with pinned versions; jQuery and Select2 removed in favour of
  `static/js/combobox.js`. No template loads anything from another origin, which is a
  precondition for the service worker in 2.4b.

### Stage 2.5 — Notification centre and expiry alerts (merged)

Alerts are **derived, never stored**: every one is a fact about the state of the business
right now, computed on read. There is no read/unread, because a stored alert can be
dismissed while the thing it warns about is still true — and then the screen says all is
well while the stock is still at zero. Expiry alerting is opt-in per item group (D1).

Because the page deliberately spans modules, it also crosses permission gates, so
`notifications.for_user()` filters by permission and **both** the page and the badge count
go through it — a badge counting what the page then withholds is its own small bug.
`ALERT_PERMISSIONS` is the map: overdue credit needs `credit.view`, plan and trial alerts
need `settings.manage`. Stock alerts need only the `products.view` the page already asks
for. Any new alert kind touching another module must be added there.

### Stage 2.5b — The subscription lifecycle (`services/subscriptions.py`)

`subscription.status` was written in exactly two places — a confirmed payment, and a plan
changed by hand in the console — so a trial that ended three weeks ago still read
`trialing` forever. The console showed the contradiction: plan "Kiosk" beside status
"Trial" on the same row.

**The governing rule: autonomous is not authoritative.** `limits.effective_plan()` works
entitlement out from the dates on every read and stays correct whether or not anything
here has ever run. This module only makes the stored status agree with it. A missed run
cannot grant a paid feature or lock out someone who paid — which matters, because the app
runs on an instance that sleeps and GitHub's scheduler drops runs when it is busy.
`tests/test_subscriptions.py` asserts that directly, across all six lifecycle states:
reconciling never changes what a business may do.

Three transitions: `trialing → free` when the trial ends, `active → grace` when the paid
period lapses, `grace → free` after `GRACE_DAYS`. Grace exists because mobile money cannot
renew on its own, so a lapse means "they have not paid *yet today*", not "they left".

**The trap it guards.** `effective_plan` reads `status == 'free'` as "on the plan named
here, with no expiry" — that is how a comped account works. So a downgrade must rewrite
`plan_id` to the free plan, not just the status; flipping the status alone would grant the
paid plan permanently and it would never expire again. If the free plan is not seeded,
`reconcile` raises rather than guessing.

Two triggers, plus a manual one:
- **Lazily**, `before_app_request`, throttled to once a day per signed-in user through a
  session marker. Failure is swallowed and logged — nobody asked for a reconcile, they
  asked for the dashboard.
- **On a schedule**, `POST /api/v1/cron/subscriptions`, guarded by `CRON_SECRET` compared
  with `hmac.compare_digest` and 404 when unset. CSRF-exempt, which is only safe because
  it takes no input and is idempotent. Called by `.github/workflows/subscriptions.yml`
  daily at 02:10 UTC.
- **`flask subscriptions-reconcile [--dry-run]`** for when the scheduler has been down.

The console now derives the badge from `due_transition()` rather than reading the stored
column, so the two columns can no longer disagree.

**435 tests passing**, locally and under bare `pytest` on CI-resolved versions.

### F-46 — The first-sign-in password gate had no way through (fixed)

Found by the user on the live site, signing in as their own employee for the first
time. A staff account is created with `must_change_password=True`, and
`enforce_password_change` correctly bounced every route to `/auth/change_password` — but
that template defined only `{% block auth_content %}`, which `base.html` emits solely for
signed-out users. A signed-in staff member therefore got the sidebar, the banner, and no
form. No way forward, no way to work. **The same trap as `offline.html` earlier in Stage
2.4**: the two blocks look interchangeable and are not.

`base.html` now takes a `standalone` flag so a signed-in page can use the centred shell,
and the route passes it. Three further things came out of it:

- The banner arrived two and three at a time. The alert-badge `fetch` runs on every page
  and is blocked by the gate too, so each background request queued another flash into the
  session for the next render. The flash is gone entirely — the page states its own reason,
  which cannot accumulate.
- API requests got a 302 to HTML. They now get `403 {"code": "password_change_required"}`,
  matching the `unauthorized()` handler's reasoning.
- `.auth-shell` reserves the 60px the fixed mobile header occupies. The card centred over
  the full viewport, so any card taller than the screen pushed its own heading behind that
  bar. This also un-clipped the logo on the login page.

**Why it shipped:** every fixture in `conftest.py` sets `must_change_password=False`, so no
test ever walked through the gate. `tests/test_password_change.py` now covers it, including
that logout stays reachable — otherwise a mistyped temporary password traps someone.

### F-47 — Password recovery, done by a person (implemented; pending merge, PR #11)

Chosen over email-based reset because it needed no provider, no domain and no spend, and it
closed a live risk the same day. Prompted by asking what was next: the app was live with
real accounts and **no recovery path of any kind**. An Owner could add staff and edit their
permissions but could not reset a password, and neither could the console — so the everyday
case (a clerk forgets theirs on a Saturday) was as stuck as the Owner case, and the only
real fix was shell access to the production database.

What made this cheap is that F-46 had just repaired the change-password gate. A temporary
password plus `must_change_password` is now a complete flow, so recovery is: issue one,
relay it, and the gate forces the holder to replace it before they reach a single page.

Two levels, one shared `services/passwords.py` — two implementations would drift, and the
one that drifted would be the console, used rarely and under pressure:

- **Owner → their own staff**, `users.manage`, scoped to the business. The common case, and
  the vendor is not involved in it.
- **Vendor → anyone**, from the console or `flask reset-user-password`. The last way back
  in, for an Owner who cannot be helped from inside their own business.

Details that carry weight:
- The generated password avoids every character people misread — no `O`/`0`, `I`/`l`/`1`,
  `S`/`5`, `B`/`8`, `Z`/`2` — and is uppercase in hyphenated groups of four. It gets read
  down a phone line or typed off a WhatsApp message.
- It is shown **once**, in a flash, and stored nowhere in plain text.
- Every reset lands in **the tenant's own activity log**. A console reset is signed
  `user_id=None` and names the admin, so an Owner can see the vendor did it. Asserting that
  needed a client holding *both* a console session and a tenant session, because with no
  tenant session `user_id` is `None` either way and the test proved nothing.

**Known gap, deliberate:** a reset does not invalidate sessions the account already has
open. The threat model here is a locked-out user, not a compromised one — there is no live
session in the case this solves. Doing it properly needs a token column on `User`, a
`get_id()` override and a migration, which is its own unit.

### F-45 — Onboarding and trial messaging (implemented; pending merge)

New businesses were told nothing. The trial was never named before signing up, nothing
guided the first hour, and a downgrade was discovered by finding a feature gone.

`services/onboarding.py` gives three things:

- **The trial, named at registration.** `trial_days` comes from a context processor rather
  than each render call — the register page has three separate `render_template` calls, and
  passing it to each is how the fourth one ends up saying nothing.
- **A setup checklist that ticks itself off from real data** — product, supplier, order,
  goods received, sale. No stored progress, so it cannot claim a step is done when the row
  was deleted, and nobody has to dismiss anything. **All five answered in one query**; five
  separate `EXISTS` calls put the dashboard over its query budget the moment it shipped.
  It disappears entirely once complete. `endpoint`/`params`, not built URLs, as with alerts.
- **A countdown, then an explanation.** `trial_state()` has exactly three phases: days left
  while trialing, a notice for `ENDED_NOTICE_DAYS` (14) after the downgrade, and silence for
  a paying customer. A banner that is always there is a banner nobody reads.

Two decisions worth keeping:

- **Deliberately quiet about the free tier while the trial runs.** It stays listed on
  `/billing/`, but naming it in the countdown answers "what happens if I do nothing?" at the
  moment we would rather they considered paying. The *end* notice does say plainly what
  happened — a surprise downgrade loses the customer.
- **`status == 'free'` is not enough to conclude a trial lapsed.** A comped account reads
  identically, and telling those customers their trial ran out would be wrong. The ended
  notice requires an actual `trial_ends_at` and a free effective plan.

Only the dashboard carries it. A countdown on all fifty routes is the same mistake that
made expiry alerts opt-in.

**Still open:** the user has further onboarding requirements to add from memory.

### F-48 — Three tests that failed only across midnight (fixed)

`TODAY = datetime.date.today()` is captured at module import in thirteen test modules. Three
tests posted `TODAY + 1 day` and asserted it was rejected as a future date — so a suite that
started before midnight and reached them after it posted a date that had since become
*today*, which is correctly accepted. The test then failed having proved nothing.

Caught when the full suite finished at 00:14. The three boundary tests (receipt date,
payment date, sale date) now call `datetime.date.today()` at the point of use. The other
uses of `TODAY` have wide enough margins that a rollover cannot flip them.

### F-49 — The sidebar folds into groups (implemented; pending merge)

Fifteen links in one flat list, which is past the point where anyone reads a menu. The four
labelled sections — Catalogue, Sales, Purchasing, Administration — are now collapsible,
taking the resting sidebar from fifteen rows to eight. Dashboard, Needs attention, Products
and Reports stay flat: they are single destinations, and burying the most-used pages one
click deeper to tidy the list would be a bad trade.

Bootstrap's Collapse drives it, so there is no new dependency and the accessibility comes
for free once `aria-expanded` and `aria-controls` are set.

Three things that were easy to get wrong:

- **The permission guards are unchanged.** A group whose children are all hidden must not
  render its own heading either, or a clerk sees "Administration" opening onto nothing.
  `test_the_group_count_matches_what_the_person_may_use` counts the groups rather than
  spot-checking, because an extra heading is the exact failure.
- **The group holding the current page always opens**, whatever was remembered. Landing on
  Settings with no indication of where you are is what makes a folded menu feel broken.
- **The remembered state is opened by class, not through `bootstrap.Collapse`.** Constructing
  it on load runs the open transition every time, so the sidebar visibly unfolds itself on
  every navigation. A corrupt `localStorage` value is caught: a parse error inside a
  `DOMContentLoaded` handler kills every listener registered after it, including the mobile
  drawer toggle.

`tests/test_navigation.py` pins the full set of Owner links by id, so losing one in a future
restructure fails there rather than being found by a customer who cannot locate Brands.

## In Progress

- Nothing. Stage 2.5, the subscription lifecycle, F-46 and F-47 are committed.
- **Next: F-45**, onboarding and trial messaging. Chosen by the user, ahead of
  Stage 2.6 — supplier scorecards need 20–30 purchase orders to show anything, and
  there are no real customers yet, so the work that matters is what turns a signup
  into one.

## Next Up

1. **Stage 2.6** — Supplier scorecards (last: needs 20–30 completed POs to show anything)
2. **Stage 2.7** — Smart reorder
3. **Stage 2.8** — Dashboard rebuild
4. **Stage 2B** — Paystack billing flow. **Not blocked any more, but not decided** — the
   registration premise was wrong and the account is pre-approved. See Open Questions:
   no payout has been received, and neither collection path has taken real money yet.
5. **Stage 3** — Interface revamp (light theme, self-hosted assets, barcode sale entry,
   branded invoices)

## Open Questions

- **Self-service password reset still does not exist (F-43), but the lockout risk is
  closed.** Recovery is now done by a person rather than by email — see F-47 below. What is
  still missing is the customer doing it themselves at 9pm without contacting anyone, which
  needs an email provider, an API key and ideally a domain. `auth/models.py` even comments that email "must identify
  a person, because every identity-recovery flow depends on it", and then no such flow was
  built. Blocked on nothing but a decision: sending email needs a provider (Resend, Brevo,
  Mailgun), an API key, and ideally a domain — `onrender.com` senders land in spam.
  Write the sending layer behind an interface, the way `billing/providers.py` is done.
- **Email verification (F-44).** Wanted, and shares the whole dependency above, so it is one
  unit with password reset: infrastructure → reset → verification, in that order. Must be
  **soft** — the account works immediately with a "confirm your email" nudge — because a
  hard gate means one undelivered email costs a customer on a phone with patchy data.
- **Onboarding and trial messaging (F-45).** New businesses are told nothing about the
  14-day full-access trial at registration, and there is no activation guidance after it.
  Planned shape: trial terms on the registration page, a welcome screen, a **setup checklist
  that ticks itself off from real data** (not a modal tour — those are a lot of JavaScript
  for something people click past), and a countdown banner. Deliberately does not advertise
  the free tier at signup; it stays listed on `/billing/` and the *end* of a trial must say
  plainly what happens next, because a downgrade discovered by surprise loses the customer.
  Requested 2026-08-08; user has more requirements to add from memory.

- **Promotional discounts do not exist.** Point-of-sale discounting works (a per-line
  price reduction, permission-gated, capped, audited) now that the ceiling is settable.
  What has never been built is a *scheduled* discount attached to goods — "10% off this
  brand until Friday", or a customer price tier. That is a distinct feature: it needs a
  price-rule model, a date window, and a resolution order when rules overlap. Raised by
  the user; not scoped or scheduled yet.
- **Paystack — open, not decided (B5). Reopened 2026-08-09.** The original reason for
  deferring was that Paystack needed a registered Ghanaian business and a corporate bank
  account. **That premise turned out to be wrong for the tier that applies here.** Paystack
  Ghana's *Starter* business type needs no registration certificate: a government ID, a
  TIN, a GPS address, and a **personal** bank or mobile money number to settle into, with
  every name matching. The user's account now reads **Pre-Approved**, meaning live payments
  are accepted while background compliance checks continue; payouts may be paused during
  those checks, and the status moves to Approved on its own. Watch for *Needs Attention* —
  that is the one that restricts payouts, usually over a name mismatch.
  (Note the trap: choosing "Sole Proprietorship" moves you into the *Registered* category,
  which **does** require a Certificate of Registration. Starter is the tier without it.)

  **Still undecided, and deliberately so.** Three things are unknown:
  1. **No payout has ever been received.** Until one lands, Paystack is unproven here.
  2. **The manual flow has never been exercised with real money either** — no customer has
     ever subscribed, so neither path has been tested end to end in production. Testing
     either one needs a real subscriber, which is the actual blocker.
  3. **Whether momo can recur through Paystack is unverified.** The finding that Ghanaian
     mobile money has no reusable authorisation predates this and was never re-checked
     against Paystack specifically. If it holds, automation only changes *who presses
     confirm*, and the manual path stays necessary for momo payers regardless — Paystack
     would sit *alongside* it, not replace it. Worth asking Paystack directly.

  **No code should change until at least (1) and (3) are answered.** Nothing is blocked by
  waiting: `billing/providers.py` exists precisely so a `PaystackProvider` is additive, and
  the confirm/reject logic, console and subscription lifecycle are provider-agnostic.
  Taking business payments into a personal wallet remains a bridge, not a destination —
  wallets have monthly ceilings and mixing business with personal money is unpleasant at
  tax time.
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
- **Console login throttling.** `/platform/login` has no rate limiting. It is a single
  unadvertised account with a 12-character minimum, so the exposure is small, but a proper
  limiter needs a storage backend (Flask-Limiter with Redis, or a database table) and the
  free tier has neither. Decide before the console is worth attacking.
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
