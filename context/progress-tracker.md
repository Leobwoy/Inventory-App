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
  `static/js/combobox.js` (itself since deleted — the product picker replaced it, see
  Stage 3). No template loads anything from another origin, which is a precondition for
  the service worker in 2.4b.

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

### F-50 — An interactive guided tour (implemented; pending merge)

Requested directly, and it overrides the F-45 note that said not to build one. `tour.js` is
hand-written — no library, self-hosted like everything since 2.4a, because a service worker
cannot reliably cache a cross-origin response and this has to work on a market-day
connection.

Seven steps, each anchored to a real element, with a spotlight, an arrow, and a bubble
explaining what the thing is for.

**The property the design rests on: a step whose anchor is not in the DOM is dropped.** The
sidebar is already permission-gated, so a Sales Staff member has no `#nav-group-admin` for a
step to attach to and is never walked through Settings. There is deliberately no second list
of who-sees-what to drift from the first. Verified live rather than only in tests: on a
business that had finished setup the tour reported "1 of 6" rather than 7, having dropped
the checklist step by itself.

**Nav steps open the drawer.** Below 992px the sidebar is off-canvas, so a step pointing at
a nav item points at nothing; the tour opens the drawer, waits for the slide, points, and
closes it after. It also opens a collapsed group first (F-49), or the highlight lands on a
zero-height element behind a folded panel. This is why the sidebar had to land first — the
tour points at things, and all of them were about to move.

**Nothing traps you.** Skip advances past a step, × and Escape end the tour. They are
different actions, and the user asked for both.

**Told once.** `User.tour_seen_at` (migration `d1b58e0472a9`), not localStorage: the question
is whether this *person* has been shown the app, not whether this browser has, and a
wholesaler using the shop tablet and their own phone should not be toured twice. Closing
early counts — someone who shut it on step two has answered, and asking again tomorrow
ignores that. A "Show me around" link beside the checklist replays it, without which anyone
who closed it on step one would have no way back.

**Test weakness worth knowing.** pytest cannot execute browser JavaScript, so several tests
in `tests/test_tour.py` assert that a mechanism is *present* in `tour.js` rather than that it
works. They would pass against code that is there but broken. The behaviour was verified in
the browser instead, at both desktop and 375px.

### F-51 — Three things found by using the app (implemented; pending merge)

**The sidebar buttons rendered as unstyled browser chrome.** Not a CSS bug: the rules were
correct and present. `static/css/style.css` is in the service worker's `PRECACHE` and served
**cache-first**, so a browser holding the `tracktrack-v4` cache kept the stylesheet from
before the nav groups existed. No amount of reloading helps, because the worker never asks
the network.

Bumped to `v5`, and added `tour.css`/`tour.js` to the precache list. More importantly this
now has a guard: `tests/test_pwa.py` fingerprints every precached file and fails if one
changes while `CACHE_VERSION` does not, printing the line to paste. It would otherwise recur
on every CSS or JS change, and it presents as a styling bug rather than a stale file. It
escaped the browser verification because that loaded a saved page directly, bypassing the
worker entirely.

**Two dashboard links pointed at the wrong place.** The "Low Stock Items" card opened the
stock level report — named for the number on it rather than its destination — and is now
"Stock Level Report". "View All" beside the low stock heading went to `/products/` with no
filter at all, showing the entire catalogue.

New page `/products/low-stock`, derived like the alerts: nothing stored, no dismiss, a
product leaves the moment stock returns above its reorder level, because handling it *is*
receiving the stock. It includes products at zero, unlike `notifications.low_stock` — the
alerts keep low and empty apart because the severities differ, but this page answers "what
do I buy", and zero is the most urgent answer to that. **Both** stock alerts now point here:
one question, one destination, with the severity distinction kept where it belongs, in the
alert list.

**A customer's statement was unreachable except through Money Owed.** Which means a customer
who has always paid on time — and so never appears in Money Owed — had no reachable history
at all. Added to the Customers row, gated on `credit.view` **and** `credit_ledger`, because
the statement route is gated on both: without the first a clerk gets a button that 403s,
without the second a Kiosk business gets an upsell disguised as a broken link.

### F-52 — Review fixes on the tour, the sidebar and the trial notice (implemented)

Seven findings from the bot's review of F-49 through F-51. All seven were real.

**Two were mine claiming protection that did not exist.**

`JSON.parse('null')` does not throw — it returns `null`, so the `try/catch` around the
`navGroups` read never fired, and indexing `null` threw a `TypeError` *inside*
`DOMContentLoaded`. Everything registered after that point never binds, **including the
mobile drawer toggle**, so the menu button stops working on a phone. The commit message for
F-49 stated that a corrupt value was caught. It was not. The parse now has to yield a plain
object or it is discarded.

The tour set `aria-modal="true"` — which announces the rest of the page as inert — while
`pointer-events: none` let clicks through and nothing trapped Tab. A keyboard or screen
reader user could walk straight out into dimmed, unreachable content. It now saves focus on
open, traps Tab among the enabled controls, restores focus on close, and the dim absorbs
clicks.

**The rest.** `tour_seen` was a read-then-write on a shared row, against invariant 8; it is
now a conditional `UPDATE ... WHERE tour_seen_at IS NULL` with the audit entry written only
when exactly one row moved. The trial countdown uses `subscription.is_trialing`, so a lapsed
trial the lifecycle job has not reconciled yet stops sitting on "0 days left". The ended
notice now requires `trial_ends_at <= now`: a future date gave a *negative* age, which is
trivially inside the notice window, so the page announced an ending that had not happened.
And the Sales nav group now opens for `credit.view` as well, or someone holding only that
permission had Money Owed rendered inside a group that never appeared — present in the
template, unreachable on the page.

**The fingerprint guard earned itself immediately.** Changing `tour.js` and `tour.css` made
`tests/test_pwa.py` fail on the first run after it was written, naming the fix. Bumped to
`tracktrack-v6`.

### Stage 3 — Interface redesign (in progress)

Full redesign, designs approved before code. **Direction: B on desktop, C on phone** —
frosted glass and density where there is a big screen and no glare; solid surfaces, no blur,
thicker borders and bottom-tab navigation below 768px, because the app is used one-handed in
a market doorway in full sun.

Design lives in `design/` and in the Claude Design project **TrackTrack**. `tokens.css` is
generated by `design/build_tokens.py` and gitignored — it embeds the icon font so mockups
stand alone. The user built the ten page mockups in a companion project; their `shell.css`
extends these tokens with toolbars, chips, form grids and breadcrumbs.

**Decided:** new behaviour their mockups imply — a plan-limit alert, per-customer credit
rows, one-click purchase orders from an alert, chip filters — is **deferred**. Phase C
restyles using what the app already does; those become their own units afterwards, each
testable alone, so the redesign never stalls behind a half-built feature. The phone keeps
five tabs (Today, Sell, Stock, Owed, More); Needs attention is reached from Today.

**Rejected, with reasons:** an activity feed on the dashboard — the only source is the audit
log, which is an `advanced`-tier feature, so Kiosk, Shop and Depot customers would open the
dashboard to an empty panel. That column shows Needs attention instead, which is derived,
already permission-filtered, and empties itself.

**B1 — tokenised, appearance unchanged.** 33 literals became 14 tokens; every one was a
black or white wash, which is exactly why a light theme could not exist. `--bg-dark` renamed
to `--bg-page`. Removed the unused `--accent-secondary` and the Google Fonts `@import`,
which sat after a rule and has therefore been ignored by browsers since it was written — the
app has never loaded Inter and has always fallen back to generic `sans-serif`. Verified in
the browser: all 14 tokens resolve to exactly the literals they replaced.

**B2 — theme plumbing, still no colour change.** `User.theme_pref` (`system`/`light`/`dark`,
migration `e2c93f5a71b8`), a context processor, `data-theme` + `data-bs-theme` on `<html>`,
a blocking pre-paint resolver, and `POST /auth/theme` (login-gated only — Settings is
Owner-only and business-wide, and the clerk in the doorway is who needs light).

**Measured, not assumed:** with `data-bs-theme` absent, Bootstrap's components are
byte-identical to `data-bs-theme="light"`. Every modal, dropdown, offcanvas and toast has
been running Bootstrap's *light* theme inside this dark app since it was built, surviving
only because `style.css` overrides the handful in use. Setting the attribute fixes it.

**Contrast findings carried into the palette:** the old accent `#3b82f6` is 3.98:1 on the
dark card — already under AA for body text; dark now uses `#60a5fa` with `#06142b` on top.
The obvious light-theme slate `#64748b` fails at 4.2:1, so light uses `#52627a`. The light
accent went to `#1d4ed8`, not `#2563eb`: I computed 4.60 for `#2563eb` against the wrong
surface (`#eef2f7` rather than the palette's `#e9eef5`), told the browser its 4.43 reading
was measurement error, and was wrong. Measure against the colour actually in the palette.

## In Progress

- **Stage 3 — the interface redesign.** Shell complete (C1): tokenised palette, light theme
  with a per-user switch, the sidebar narrowed to a 140px icon-and-label rail, and phone
  navigation moved to a bottom bar. **C3, the sale form, is complete** — see below.
  **C2, the dashboard, is still the old layout** and was skipped by mistake, not by
  decision; it is the next thing to pick up. The remaining pages are still old layouts in
  new colours.
- **Answered 2026-08-13: Stage 3 first, as a full redesign.** 2.6 and 2.7 both score
  suppliers from purchase history and need 20–30 completed orders before they show
  anything — with no real customers yet, both would ship as empty screens. The user chose
  the interface revamp instead, and chose a full redesign over a recolour: designs approved
  in Claude Design first, then built page by page. Direction B on desktop, C on phone.

- **CodeRabbit review, round 2 — 14 findings, all verified valid, all fixed.** Worth keeping
  two of them. The nav-label test ended in `or word in body`, which every word it checks
  satisfies from the page content alone — it would have stayed green with the labels
  stripped out entirely. And the media-query test sliced from `@media (max-width: 991px)` to
  the end of the stylesheet, so a rule in a *different* block answered for the one under
  test; there are two such blocks. Both now assert against a bounded region, and both were
  falsified. The contrast sweep also had a `length > 90` filter that was quietly skipping
  most of the prose on every page — removing it took the swept node count from 942 to 1266,
  still with zero failures.

**C3 — Record a sale.** Two panes, one form: what is being bought, then who bought it and
how they paid. The split is presentation only — one POST, one route, nothing held in the
session between steps, and with no JavaScript both panes render and the page works exactly
as it did. Which pane opens is decided *server-side* from where validation failed, because a
rejected field behind a hidden pane is a page that reloads looking unchanged. On a desktop
the running total sits beside the items; on a phone it sticks to the bottom of the screen
directly above the tab bar. The two dropdowns became radio chips, styled through
`input:checked + span` rather than `:has()`, which the older Android WebViews in this market
do not support and would have failed at silently and totally.

Three real defects found by measuring the page rather than looking at it:

- **The sale date was `required` with no default**, so the browser refused to submit until
  someone picked today's date by hand — every sale, from a phone. The first end-to-end
  attempt produced no POST at all and no message. Now `default=date.today` (the callable: a
  frozen `date.today()` would have the server offering the day it booted a week later).
- **`.btn-lg` has never worked anywhere in the app.** This file's own `.btn { padding }`
  rule matches at the same specificity as Bootstrap's `.btn-lg` and comes after it, so every
  large button in every page has been rendering at the ordinary size.
- **A required field on a hidden pane cannot be focused**, and a browser that cannot focus an
  invalid control refuses to submit and says nothing — no bubble, no POST. Guarded on both
  the step change and the submit.

Measured at 375px: every tap target ≥ 44px, no horizontal overflow, the sticky total bar
lands exactly on the tab bar's top edge. Contrast clean in both themes, worst 5.32:1 light
and 6.10:1 dark.

**The sweep had a blind spot, and it is closed.** It measures what is *visible*, so the
second pane of a two-pane page was invisible to it — `sale` dropped from 80 checked nodes to
78 when the page gained a pane, and said nothing. `capture.py` now takes a second shot of
any page in `PANED` with every `<script>` stripped, which leaves the server's own
`data-steps="off"` in place and both panes on screen. That is also the state a phone whose
script failed to download is in, so it is worth measuring in its own right. `saleboth`
checks 100 nodes against `sale`'s 78.

Getting there cost an hour to a byte. The strip regex was written with `` in it, which
became a **literal backspace character** in the source; `grep` and the terminal both render
0x08 as nothing, so the line read perfectly, matched no scripts at all, and the sweep went
on reporting the same node count. `findall` with the same pattern typed fresh matched 11.
Only printing `repr()` of the source line found it. The pattern is now built from `chr()`
calls, and the capture warns if the stripped copy is not in the no-script state.

**C3 fix + C6 — the product picker.** Reported from the running app with two screenshots: on
the sale form the product box read "BelA", and on Create Purchase Order the quantity and cost
controls had collapsed into nested, disconnected boxes.

Measured before touching anything. At 1280px the sale table got 583px and the product input
**60px**; at 1440px — an ordinary laptop — it was **98px**, against a longest product name
needing 169. Five columns wanted roughly a 1500px window. Notably this was **desktop-only**:
on a phone the row stacks and the field gets 301px, so the C3 rebuild had fixed the phone and
broken the laptop.

The answer was the user's own designs, which show every cell in both the sale cart and the PO
order-lines table as **plain text**, with "Add line" beneath. Products are now chosen in a
dialog: `templates/_partials/product_picker.html` + `static/js/picker.js`, one per page,
serving every line. Bootstrap's Modal, because its bundle was already loaded and precached on
every page — the first modal this app has ever had. The `<select>` stays, keeps its name, and
stays the source of truth; `picker.js` hides it, never the server, so no-JS still works.
Result: product name space went 60px → 168px at 1280px, and 15 of 16 catalogue names now fit
on one line.

Three defects fixed alongside, all worse than cosmetic:

- **A purchase order could only ever have one line.** No add-row control, no cloning script;
  the route never appended entries. Every PO this app has created has had exactly one product
  on it. Now adds and removes lines, with the sale form's renumbering.
- **`purchases/routes.py` crashed on the "product no longer available" path**, re-rendering
  without `product_uom` which the template feeds to `|tojson`. It raised inside the `try`, so
  `except Exception` swallowed it and replaced that specific message with the generic
  "Something went wrong". Nobody has ever seen the real one.
- **The PO page rendered no validation errors at all** — no `is-invalid`, no
  `invalid-feedback`. A refused order came back looking identical to the one sent. Also
  `order_date` had no default, the same silent submit-blocker the sale form had.

Goods receipt became one card per line — seven columns, five read-only, and the three that
are typed into were sharing the leftovers on the page where a typo costs real stock.

**Corrected belief, recorded because the obvious guess was wrong:** a *gap* in WTForms
indexes (`items-0` + `items-2`) is harmless — it compacts. What loses a line is a
*collision*, which is what removing a middle row causes when the next row is named from
`length`. Two lines then post under one name and WTForms reads the first. A test asserting
the gap theory failed, which is how this was found.

**The sweep's dialog blind spot is closed too.** Bootstrap's `.modal` is `display: none`
until shown, so an ordinary capture measures none of it and reports clean without looking.
`capture.py` now takes a `dlg` shot with the modal forced open and its list filled from the
same `<select>` the script reads. 2024 nodes swept across 22 captures, zero failures.

**Follow-up: the combobox is gone.** `static/js/combobox.js` and `static/css/combobox.css`
were the picker's predecessor and had no callers left once the dialog landed — but they were
still in `PRECACHE`, so every user downloaded ~8KB of dead code on first visit. Both deleted,
dropped from `PRECACHE` and from `VENDORED` in `tests/test_assets.py`, `CACHE_VERSION` bumped
to `tracktrack-v16`. They were kept for a while as a candidate for the customer and supplier
selects; nothing was ever scheduled, and git history is a better home for that than the
precache list. A future searchable select should widen the picker or restore the file from
history rather than invent a third pattern.

**Follow-up from the running app — three fixes.** Reported with a screenshot: a quantity
over 9 showed only its first digit, and nothing indicated the product box could be tapped.

Measured at 1100px, both were worse than reported. The quantity input was **20px** with
**5px** of room inside it, so not even one digit rendered, and the product name had **57px**
— worse than the 98px the picker had just fixed. Three separate causes, all mine:

- `min-width: 0` on the input is explicit permission to collapse, and it collapsed.
- The column widths were written outside any media query, so `width: 9rem` still capped the
  quantity cell at 144px on a phone with 300px going spare.
- The summary panel started sharing the row at 992px, but the row needs about 610px and the
  items pane only reaches that at roughly 1330px. It drops beneath the items below 1400 now,
  which is arithmetic rather than taste: 207 for a name, 157 for the stepper, 112 for the
  price, 80 for the line total, 54 to remove it.

**The lesson is the measuring, not the CSS.** The first pass checked 1280 and 1440 and
declared victory; every width between 992 and 1200 was broken and unlooked-at. Layout is now
measured at 375, 1024, 1280 and 1440 as a matter of course.

| Viewport | Quantity box | 4 digits | Name space | Longest name fits |
|---|---|---|---|---|
| 375 | 227px | yes | 275px | yes |
| 1024 | 56px | yes | 281px | yes |
| 1280 | 56px | yes | 385px | yes |
| 1440 | 56px | yes | 216px | yes |

**The affordance.** The picker button's border computed to two thirds of a pixel at 10%
white — invisible on a dark card — and the search icon was hidden the moment a product was
chosen, which I had done deliberately to reclaim 24px. A bad trade: it bought width with
discoverability. There is a chevron pinned to the right now that never hides, and a border
on its own token (`--input-border-strong`) that can actually be seen.

Written as `<i class="bi bi-chevron-down">` markup rather than a CSS `content` escape,
because a unicode escape written through tooling arrived here as a **control character for
the third time** — once as a backspace in a regex, twice as a form feed in this rule, the
second time inside the comment warning about the first. Control characters render as nothing
and read as correct. The rule is now: never write one; use markup or `chr()`.

**Supplier prices** gained an instant filter. Deliberately unlike the five paginated list
pages that use `services/listing.py`: this page has no pagination, renders every row at once
(15 cards over 5 screens), so everything being searched is already in the browser. Matched
against a `data-search` attribute holding name and SKU, not the card's text — a card also
holds supplier names and prices, so searching "2" against its text would match every product
whose price contains one.

**C2 — the dashboard.** Skipped by mistake when the sale form was rebuilt, so it sat on the
old layout two commits longer than it should have.

Four stat cells, then the trend and what needs doing. Every stat is a link: a number you
cannot act on is a number you stop reading. The week's takings now carry a comparison with
the week before — the old page gave a total with nothing to judge it against.

**The right-hand panel is Needs attention, not an activity feed**, and this is the decision
recorded back in the design phase finally implemented. A feed can only come from the audit
log, which is `advanced`-tier, so Kiosk, Shop and Depot would open the page to an empty panel
every day forever. Needs attention comes from `services/notifications.for_user()` — already
permission-filtered, sharing the nav badge's per-request cache so the two cannot disagree,
and it empties itself when the work is done.

**Money owed is gated twice:** the credit ledger is a paid feature, and reading the debt book
is a permission of its own. Worth recording that the Sales Staff preset *does* include
`credit.view` — they are the people who take the payments — so a test asserting the
permission gate has to set permissions explicitly rather than lean on a role name.

**The chart's eight hardcoded colours are gone.** Chart.js paints to a canvas and cannot
inherit a CSS variable, so every colour in it was the dark theme's; anyone on light got a
chart drawn for a background that was not there. It reads the tokens at build time and
redraws on `tracktrack:theme` — plus a `MutationObserver`, because the sidebar toggle
rewrites the attribute directly rather than firing the event.

**A phone target fix that should never have been scoped.** `min-height: 44px` on buttons was
written as `.sale-form .btn` when the problem was first measured there. The dashboard's own
"Record a sale" then came out at **33px**, because a page-header rule shrinks buttons on a
phone and overrides `.btn-lg` entirely. It applies to every button now.

**The query-count test caught a real regression, and the budget was raised on purpose.**
The dashboard went from 9 queries to 20: measured, Needs attention costs 10 and money owed 1.
The budget is now 22 with the reasoning written into the test.

This deliberately does *not* follow the badge's precedent. `/products/alerts/count` is
fetched after load because the sidebar renders on fifty-odd routes and computing alerts for
all of them would charge pages that never show the number. The dashboard is the page that
does show them - first on the screen, on a phone - so fetching after load would leave the
most important panel blank exactly when someone opens the app to see what needs doing.

Left undone deliberately: the route counts low stock for the Restock figure and
`services/notifications` counts it again. Worth collapsing; not worth holding the page for.

**Three tests were asleep when first written**, all the same shape: an assertion satisfied by
something other than the thing under test. An `or` across two branches that the fallback
branch satisfied; `tracktrack:theme` named in the comment explaining why it is listened for;
and a script slice running to the end of the document, which caught **base.html's own**
`tracktrack:theme` listener for the sidebar toggle. All three now scope to exactly what they
mean, and all three falsify.

## Next Up

**Stage 3 is paused after the dashboard.** Units and pricing jump the queue at the user's
direction (2026-08-17): "of importance and urgency". The remaining redesign pages resume
after it, because the product form and list are exactly where the new fields live and
rebuilding them first would mean rebuilding them twice.

1. **Stage U — Sell by the carton.** U1 schema and services, U2 the sale path, U3 the sale
   form, U4 the product form in plain language, U5 three correctness fixes. See
   Architecture Decisions below for the model and the research behind it.
2. **Stage W — The carton *is* the unit.** Follows directly from U, at the user's
   correction (2026-08-18): U treated the carton as a second price alongside the single.
   That was still backwards. W1 backup data loss, W2 the carton becomes what you type,
   W3 the purchase order names its unit, W4 the invoice, W5 stock reads in cartons,
   W6 exports name their units, W7 the sale opens on Carton.
3. **Stage 3 C4** — Products pages to the design (list, add/edit, alerts, low stock)
4. **Stage 3 C5–C8** — Money owed, purchasing lists, reports, settings, auth, print documents
5. **Stage 2.6** — Supplier scorecards (last: needs 20–30 completed POs to show anything)
6. **Stage 2.7** — Smart reorder
7. **Stage 2B** — Paystack billing flow. **Not blocked any more, but not decided** — the
   registration premise was wrong and the account is pre-approved. See Open Questions:
   no payout has been received, and neither collection path has taken real money yet.

(Stage 2.8, the dashboard rebuild, shipped as Stage 3 C2. Barcode sale entry and branded
invoices were folded into Stage 3; branded invoices already shipped as F-36.)

- **Cramped fields on goods receipt.** Reported from the running app with a screenshot.
  On `templates/purchases/receive.html` the "Receiving now" input is about one digit wide and
  "Batch number" is squeezed beside it — the row carries seven columns (Product, Ordered,
  Already in, Outstanding, Receiving now, Batch number, Expiry date) and the three that are
  actually *typed into* get whatever width is left over after five read-only ones. The fix is
  a layout change, not a width tweak: the inputs should lead. Due in Phase C6 when Purchasing
  is rebuilt; noted here so it is not lost, since it is the page where a typo costs real
  stock. Same shape of problem is likely on the sale form, which has the same pattern.

### Decision — selling by the carton (2026-08-17)

**Asked for directly:** wholesalers "sell by the crate or carton, not one-one like a
provision store", the price should be the carton price, and the add-product form's unit
fields are "confusing to a business owner… they wouldn't understand".

**What the app did.** UOM was applied on the buy side *only*. Zero occurrences of `uom.`,
`base_uom`, `purchase_uom` or `order_unit` anywhere under `sales/`. `sales/routes.py` passed
`item_form.quantity.data` straight to `stock.deduct_fefo`. Selling three cartons of 24 meant
typing 72. One price existed, per single, and nothing in the schema or the form said so.

**Research.** Ghanaian packs are 12 and 24: Club Premium Lager 330ml ships 24 × 330ml with
12-bottle cartons also sold; Voltic 500ml ships in packs of 24 across 500ml/750ml/1.5L/19.5L.
The distribution industry models three levels — each, inner pack, case pack — and the ERP
convention is that **buy units and sell units are independent**: an item may be bought in a
case, pack or each and sold in an each, a case, a pack, or not have all options for sales.
This app had one conversion applied on one side. That was the gap.

**The model.** Stock stays in base units — that invariant is what makes FEFO, batches and
`flask reconcile-stock` work, and it does not move. Only what is charged and what is typed
change:

- `Product.pack_price`, nullable. Null means a carton is `count × unit_price`. A value means
  a real wholesale carton price, which **cannot be derived** — the gap between ₵48 a bottle
  and ₵43.75 a bottle inside a ₵1,050 carton is the entire reason a shop buys a carton.
- `Product.sell_unit` — `base` | `purchase` | `both`.
- The sale line carries a unit; `deduct_fefo` still receives base units.

**The form drops the jargon.** "Base UoM / Purchase UoM / Units per Purchase UoM" became
"How is it packed? Carton of 24 bottles", "What do you sell by?", and two prices — with a
sentence reading back the derived per-piece figure, so a carton price typed into the singles
box shows ₵1,050.00 a bottle *before* saving rather than weeks later.
`uom.cost_per_purchase_unit()` already existed for this and was called from nowhere.

### Stage U progress

**U1 — a pack has a price of its own.** `Product.pack_price` (nullable, null means
`count × unit_price`) and `Product.sell_unit`. Two CHECK constraints, one overdue:
`units_per_purchase_uom >= 1` was never enforced — `uom.factor()` clamped bad counts at read
time, hiding broken rows rather than preventing them. `to_base`/`cost_to_base` now check
`has_conversion` themselves; they were correct only because both call sites happened to guard
first, and the sale path is the third caller.

**U2 — the sale path.** A sale line carries the unit it was rung up in.
`SaleItem.quantity` stays base units and `price_at_sale` stays per base unit, so the four
places that sum `price_at_sale * quantity` — `services/credit.py:47`, `credit/models.py:71`,
`reports/routes.py:94,100` — keep working untouched, as does every stock query. `sell_unit`
and `sold_quantity` are added only so the invoice can say "2 cartons" instead of "48
bottles", and both are frozen history for the same reason `list_price` is.

Three things that would have been wrong and were caught by writing the arithmetic down:

- **F-41, again, on the side the customer pays.** A carton at ₵1,000 for 24 is ₵41.666… a
  bottle; at two decimals two cartons bill ₵2,000.16 against the ₵2,000.00 agreed.
  `price_at_sale` and `list_price` widened to `Numeric(14,6)`, matching
  `PurchaseOrderItem.unit_cost`.
- **The below-cost floor compared a carton price against a bottle's cost.** Cost is stored
  per base unit; `requested` is per unit sold. A carton that cost ₵921.60 would have passed
  the floor at ₵500. It converts with `uom.cost_per_purchase_unit` now.
- **`pricing.resolve` skipped the `is_finite()` check** that `code-standards.md:131` requires
  and `api/routes.py:226` already performed. `NumberRange(min=0)` has no max, so
  `Decimal('Infinity')` reached it and came back out as the charged price.

**The widening leaked, and the suite caught it.** Two tests failed the moment
`price_at_sale` became `Numeric(14,6)`: a total read `0.300000`, and the overpayment guard
compared a tendered `800.00` against an outstanding `800.000000` and refused a correct
payment. Storage precision was right; letting it escape was not. Money now rounds once at
the boundary where a person reads or pays it — `credit.sale_total()` quantises, and the SQL
sum in `services/credit.py` rounds. The old test asserting `str(total) == '0.30'` was
asserting the *column width*, not the guarantee, and now asserts at the money boundary
instead. A new test covers what a customer is told they owe, which nothing covered before.

**U3 — the control on the page.** A Carton/Single toggle inside the quantity cell, not a
sixth column: this table fought for width once already and a new column would take it
straight back off the product name. It shows the business's own words — "pcs" and "carton",
not "Single" and "Carton" — because those are the words they typed when they set the product
up. It appears only where there is a real choice, and `units` is filtered server-side so the
control cannot offer what the server would refuse.

Everything the page needs travels in the **existing** `product_prices` variable rather than a
new one. That template is rendered from five places in this route, and the purchase order
page has already shipped a bug where one path forgot a variable the template required.

Measured at 375 / 1024 / 1280 / 1440: quantity holds four digits everywhere, the product name
still fits, the toggle never clips, nothing under 44px on a phone, no horizontal overflow.

**The contrast sweep earned its keep again**, and cost an hour doing it. The chosen unit
rendered at 2.43:1 on dark and 2.66:1 on light — the word saying whether you are selling one
bottle or twenty-four, unreadable on its own highlight. `background` from that same rule
applied; only `color` lost. Established: the rule matches, `--on-accent` resolves on the
element, the winning declaration is inside `style.css` (disabling it changes the result),
appending an identical rule later does not win, `!important` does, and no `!important` colour
rule in the file matches that element. It is now `!important` with all of that written beside
it, because the readability of that word is not worth more of the budget than it already
took. **A large part of the hour was spent measuring a cached stylesheet** — every reading
after every edit came back identical, which is the signature, and I read it as "the fix
failed" four times before recognising it.

**U4 — the product form in the owner's words.** The three fields that read "Base UoM",
"Purchase UoM" and "Units per Purchase UoM" are now a sentence you fill in — *One is called
`bottle` sold in packs of `24` called a `carton`* — and underneath it the form reads back what
that means: *"You sell this by the carton of 24 bottles. A carton is ₵1,050.00 — that works
out at ₵43.75 a bottle."*

That sentence exists for one specific mistake. A carton price typed into the single price box
produced a product listing at 24× its real price, and nothing on the old form said which unit
either box was in. It now answers back *"Check the single price - ₵1,050.00 for one bottle
looks like a carton price"* before Save rather than after the first sale.

The pack price and the sell-by dropdown appear only once a real pack is described, and the
dropdown speaks the words just typed — "bottles only / cartons only / Both".

**Field names are unchanged deliberately.** `tests/test_audit.py` posts this exact set;
renaming them would be a schema-shaped change dressed up as wording.

**A nonsense setup cannot be saved.** "Both" on a product whose pack is one item, or whose
pack is named the same as the item, saves as singles-only — otherwise the sale form offers a
carton the server then refuses, which reads as the app being broken rather than the product
being set up wrong. A blank pack price stays **null**, not zero: null means "a pack is count
× the single price", zero would mean free.

**Two gaps of my own, found by the tests I had just written.** The form rendered a reason for
exactly *one* of seventeen fields, so a refused product came back looking identical to the
one sent — all of them explain themselves now. And the sentence had replaced the labels
entirely, leaving a screen reader three unlabelled boxes wedged between loose words; each
keeps a real label, visually hidden.

**U5 — purchasing is pack-only, and the receipt loophole is shut.**

Reported from the running app: *"no wholesaler will procure or restock in single bottles.
Everything comes in crates or carton or box."* Correct, and it made the page simpler rather
than more complex — the unit dropdown was asking a question with one answer. There is no
control now: the line states its unit in the product's own word, the server **derives** it,
and a posted value is ignored. That is a stronger guarantee than gating a control, because
there is nothing left to post past. A product with no real pack is still ordered in singles.

The unit is consistent across the app now: declared once on the product, stated on
purchasing, carried through receiving, and chosen per line only on the sale — the one place
both genuinely happen.

**The goods receipt gate.** It checked the product but never the plan, unlike order creation
twenty lines above it. My first test of it used the free plan, which cannot open that page at
all — so nothing was received and I read that as the gate working. The real case is **Shop**:
`purchase_orders` is basic tier and `uom_conversion` is standard, so Shop can order and
cannot convert. That is the plan the test uses.

**Also reported: a three-figure price losing its last digit on the sale form.** Measured, the
box had 40px of usable space when even "44.16" needs 41 — *every* price was clipped, and the
four-figure carton prices only made it visible. Fixed and checked at all four widths.

Twice in a row now an `<input>` with `width: auto` has ballooned its column: the intrinsic
size is about twenty characters, so the price column took 265px and stole it from the product
name, exactly as the quantity box did. Both carry an explicit basis.

**A bug I wrote and caught:** the "is this in packs" flag was computed one line above the
variable it reads. `var` hoists the declaration but not the value, so it was silently false —
the conversion hint vanished and the supplier comparison read ₵43.07 more instead of ₵0.75,
measuring a carton against a bottle's best price.

**A falsification that needs two mutations, recorded so it is not mistaken for a sleeping
test.** "A pack in name only is not multiplied" is protected in two places — the route
refuses to set the unit, `uom.to_base` refuses to act on it — so breaking either alone comes
back green. Both together go red.

**A gate that is defensive rather than testable, recorded so nobody deletes it as dead.**
The API path checks `uom_conversion` before honouring a posted unit, but `offline` and
`uom_conversion` are both `standard` tier, so every plan that can sync also has conversion.
They are two features sharing a tier, not one feature — and a queued sale can arrive days
after a downgrade. The product-level half of that gate *is* reachable and is tested.

### Decision — the carton is the unit, not a second price (2026-08-18)

Stage U gave the carton a price of its own. Asked why the purchase order form showed a carton
price beside a per-bottle comparison, the user named the real error rather than the symptom:

> *"We've been highly mistaken since the onset. The main unit of measurement here should be
> the carton. We don't care what a single bottle costs, because different retailers charge
> different prices for the same bottle — one shop sells Bigoo at ₵3.00 and the next at ₵3.50.
> What we care about is the carton. Selling a single bottle belongs on the sales side; it
> should not reach the purchase order side."*

Traceable to one cause: `services/uom.py` was built around the rule *everything is stored in
base units*, which is right for storage, and that assumption leaked upward into every screen
until the app was asking a wholesaler to think in bottles.

**Storage does not move.** Quantities stay in base units — that is what lets a delivery
arrive as "10 cartons and 6 loose" and what makes FEFO and batch expiry work. What changes is
everything typed and everything read.

`Product.unit_price` stays `NOT NULL` and stays stored; it simply stops being *typed*. The
form asks the carton price and the route derives the per-bottle figure via
`uom.per_base_price()`, which already existed and was called from nowhere. That deliberately
avoids the null-handling blast radius: price sorting (`products/routes.py:26-27`, where NULL
sorts unpredictably on Postgres), the offline catalogue payload, and `test_queries.py:185`.
`services/pricing.py` needs no change at all — it reads `uom.price_for()` and never touches
`unit_price`.

### Stage W progress

**W1 — the backup was losing the carton price.** Found while mapping, not by a report, and
done first because it is live data loss rather than a wrong label. `EXPORT_SPEC` omitted
`pack_price` and `sell_unit` from products, and `list_price`, `sell_unit` and `sold_quantity`
from sale lines. Every archive taken since Stage U shipped silently dropped the wholesale
price and any record that a sale was rung up in cartons; restoring one repriced a whole
catalogue at bottle rates and turned two cartons back into forty-eight bottles.

**A claimed bug that falsification disproved, kept because the write-up is the point.** The
restore path collapsed *absent* and *blank* into the same value — `record.get(column) or ''`,
and `_coerce` turns `''` into `None`. I recorded that as a second bug: an archive from before
`sell_unit` existed would pass `None` explicitly, override the model default and fail NOT
NULL. Reverting the guard left the test green, so I probed the insert directly: SQLAlchemy
treats an explicitly-`None` attribute as unset and fires the column default anyway —
`sell_unit` arrives as `'base'`. The failure cannot happen today.

The guard stays, with the comment rewritten to say that. It rescues *defaulted* columns and
nothing else, so the day a NOT NULL column without a default is added, every older archive
would stop importing — that is worth two lines. The test stays too, saying in its own
docstring that it passed before the change, because a test that cannot go red is worth
keeping only when it is honest about what it pins: the guarantee that an archive from before
the carton columns still restores.

**W2 — the carton is what you type.** The form asks two questions it never asked before -
what does a carton sell for, what does a carton cost you - and stops asking the two it used
to. `unit_price` and `cost_price` are derived on save and stay `NOT NULL`; that is the
decision that kept this contained, because making them nullable would have pushed a NULL
into `PRODUCT_SORTS`, the offline catalogue payload and every report that multiplies by
them. `services/pricing.py` needed no change at all - it reads `uom.price_for` and never
touches `unit_price`.

Loose goods keep the old path. A product with no real pack is still asked for a single
price, still saveable and still sellable, which is why the two prices are validated as a
pair in `ProductForm.validate` rather than by marking either field required: a required
field on a hidden pane blocks submit with no visible reason and no submit event to catch,
which this project has already been bitten by once.

**`cost_price` was widened to `Numeric(14, 6)`, and the reason is the round trip rather than
the sale.** The form now asks for a carton cost and stores it divided. At two decimals a
carton at 1,000 for 24 stores 41.67 a bottle, which the edit form multiplies back to
1,000.08 - so simply opening a product and saving it would walk its cost upwards, every
time. `unit_price` deliberately stays at two: it is a real per-bottle price charged in whole
pesewas, and it is re-derived from the stored pack price rather than round-tripped, so it
cannot drift. Only one screen displays a cost - the product export - and it rounds, because
the last widening leaked six decimals onto a page.

**The low-stock threshold is typed in cartons and rounds up.** Down would not just be less
safe, it would be unstable: 100 bottles at 24 shows 4 cartons, saves 96, shows 4 again -
walking the warning level down every time the product was opened. Up settles after one step.

**The audit log now records the price somebody actually typed.** It logged `unit_price`
only, which after this change is a derived figure - the decision behind it would not have
appeared anywhere.

**Three tests asserted the old direction and were rewritten rather than patched.**
`test_a_blank_pack_price_is_not_zero` asserted that a packed product saves with no pack
price, meaning "a pack is count x the single price". That is exactly what W2 reverses, so it
is now `test_a_packed_product_is_refused_without_a_carton_price`, with the old guarantee
named in its docstring and still covered at the service level in `test_pack_pricing.py`. The
form's warning inverted with the boxes: there is no singles box on a packed product any
more, so the mistake it watches for is a bottle price typed into the carton box, and the
signal is a carton selling below its cost.

**A U4 bug found by looking at the page rather than the tests.** The read-back sentence,
the sell-by dropdown and the new threshold suffix all pluralised by appending an `s`, so the
default base unit rendered as **"pcss"** - on screen for most products since U4 shipped, and
"boxs" for anyone selling by the box. There is a `plural()` helper now: unchanged if it
already ends in `s`, `es` after x/z/ch/sh, `s` otherwise.

**An hour's worth of wrong contrast readings, caught by a control.** Measured on dark, the
guard sentence came back at 2.32:1 and every field label at 1.75:1. The tell was that a
label W2 never touched measured 1.75 too - if that were real the whole dark theme would have
been unreadable since it shipped. The cause: `.glass-card` carries `transition: background
0.2s`, the Browser pane was not compositing, so the transition never advanced and the card
stayed frozen at the *previous* theme's colour while `.pack-summary`, which has no
transition, switched immediately. Every reading was near-white text composited over a
near-white surface that was not actually on screen.

**Injecting `* { transition: none !important }` before measuring is now the rule**, and it
is cheap. The real figures: the sentence is 16.36:1 on dark and 15.72:1 on light, the labels
6.10 and 6.04 - identical to the untouched control, which is the point. Layout measured at
375 / 1024 / 1280 / 1440: no horizontal overflow, nothing clipped with a five-figure carton
price, every control 49px tall.

**A permission test that broke for the wrong reason.** `cost_price` is withheld from staff
without the permission, and the test asserted the substring was absent from the page. The
new script reads the cost box when there is one, so `[name="cost_price"]` now appears in a
selector - a selector that finds nothing is not a leaked cost. It asserts against a real
`<input>` now, and covers `pack_cost` as well, which is the same secret multiplied by 24.

**W3 — the purchase order says which unit its price is in.** The reported confusion, and
the smallest fix in the stage: the box was labelled "Unit Cost", it is filled in with a
carton price, and the comparison under it quoted a per-bottle figure. Both numbers were
right and nothing said they were in different units. The label reads "Cost per carton" now,
in the product's own word, and the comparison leads with the unit being typed - *"Best so
far: ₵5.52 a carton from Accra Bulk Beverages"*, with *"That is ₵0.46 each."* as a quiet
second line. Measured against seeded data: typing ₵7.20 for that carton of 12 reads *"this
is ₵1.68 more a carton"*, which is 12 × the ₵0.14 per-piece gap.

**`services/sourcing.py` was deliberately not inverted**, and that now has a test of its
own, because "make it all cartons" is exactly the tidying somebody will attempt later. Two
suppliers who pack the same drink 12 and 24 to a carton cannot be compared on carton price:
the one with the smaller box would win every product. The comparison stays per single and
only the display scales up.

**"a pcs".** Naive articles produced *"₵0.46 a pcs"*, and `pcs` is the default base unit, so
it was the common case rather than an edge one. The line hint on the same page had already
solved this by saying *"at ₵0.46 each"*; there is a shared `per()` helper now - "each" for
pcs/pc/unit, "a <word>" otherwise - used by both pages. The product form had the same bug in
its read-back sentence.

**The substring trap, three times in one stage, once in a test I had just written.**
`'cost-unit-word' in page` passes with the span deleted, because the page's script names the
same class in a `querySelector`. Falsification caught it; the assertions match a real
`<small>` or `<span>` element now, and `hint_elements()` exists so the next one is written
correctly by default. The same shape broke `test_cost_price_field_is_absent_for_unpermitted_staff`
in W2. **Any assertion about markup on a page that carries an inline script has to match an
element, not a class name.**

**A test premise wrong for the third time in this project.** Setting `subscription.status =
'active'` and a paid `plan_id` is not enough - `effective_plan` reads `paid_through` and
falls back to Free without it, so the page under test redirected instead of rendering. The
existing tests that set only the status pass because they assert a feature is *blocked*, and
the fallback blocks it for the wrong reason.

**W4 — the invoice says what the customer bought.** `SaleItem.sold_as` and
`price_per_sold_unit` were written in Stage U2 and the migration that added the columns
states outright that "the invoice then reads 2 cartons rather than 48 bottles". No template
ever called either, so a two-carton sale printed **₵43.75 × 48** to the customer:
arithmetically correct, and not what anybody agreed to. Both invoice templates and the sales
report read in the sold unit now.

**The line total is deliberately still `price_at_sale × quantity`.** Recomputing it from the
rounded per-carton figure would be the F-41 mistake in a new place - the page would stop
agreeing with the database. What the customer reads and what was charged are the same
number, and the unit is the only thing that changed.

**Two more found while wiring it.** `bulk_invoices.html` had no number format at all on any
of its four money figures, so a carton line printed **₵41.666667** and the grand total
₵2,000.000000 - the U2 widening leaking onto a page nobody had opened since. And
`sales_report.html` printed `x48` with the same unformatted price. Both fixed here rather
than left for W6, because they are the same bug as the one being fixed.

**A struck-through discount had to scale too.** `list_price` is stored per base unit like
`price_at_sale`, so a carton discounted from ₵1,050 to ₵1,000 would have shown ₵1,000.00
struck against ₵48.00. `SaleItem.list_price_per_sold_unit` mirrors `price_per_sold_unit`.

**`uom.plural()` and `uom.quantity_label()`** put the unit words in the module that owns
them: "2 cartons", "1 carton", "48 pcs". The browser copy on the product and purchase order
forms is three lines of the same rule, kept separate because those pages compute their
sentence before anything is saved.

**The invoice had no test coverage at all** before this - the pages that a customer
physically holds. Seven now.

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
- ~~**Onboarding and trial messaging (F-45).**~~ **Done** — see Completed. One line of it was
  wrong and is worth keeping visible rather than deleting: the planned shape said a checklist
  **"not a modal tour — those are a lot of JavaScript for something people click past"**. The
  user asked for exactly that tour on 2026-08-11, twice and explicitly, and it is built (F-50).
  The reasoning was not wrong about the cost — `tour.js` is 250 lines — but it was a product
  judgement dressed as an engineering one, and it was not mine to make.

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
