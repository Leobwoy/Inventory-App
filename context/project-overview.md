# TrackTrack

## Overview

TrackTrack is a multi-tenant inventory and supplier management platform for Ghanaian
beverage and FMCG wholesalers — businesses moving bottled water, soft drinks, malt and
soya drinks by the crate. It replaces the paper book a wholesaler keeps: what is in
stock, what was bought and from whom, what was sold, and who still owes money. The
strategic bet is depth in supplier and inventory management rather than breadth:
payments and customer-facing ordering are deliberately deferred so the product is
excellent at one thing first.

## Goals

1. A newly registered business can record its first sale within ten minutes, without
   support and without touching a database.
2. Stock figures are always correct — the cached quantity never diverges from the
   authoritative batch total, and `flask reconcile-stock` reports zero drift.
3. An owner can answer "who owes me money" and "who is cheapest for this product"
   in one click each. Both were unanswerable before.
4. No tenant can read, write or infer another tenant's data through any route.
5. Floor staff cannot see cost prices or margins — a stated requirement of this market,
   enforced at the route and export level, not just hidden in the interface.
6. The app keeps working when the network drops, because market-day connectivity in
   Ghana is unreliable and a wholesaler will not accept a till that stops.

## Core User Flow

1. Owner registers a business — name, address, contact, their own name and password.
2. A `Generic` brand and `Uncategorized` item group are seeded automatically, so the
   first product is savable with zero setup.
3. Owner builds the catalogue: categories, brands, item groups, then products with
   cost price, sale price and unit-of-measure (e.g. buys in cartons of 24, sells singles).
4. Owner adds suppliers.
5. Owner raises a purchase order, entering quantities in cartons or singles. Where price
   history exists, the best known price and supplier are shown while typing.
6. Goods arrive. Owner records a receipt per line — quantity, batch number, optional
   expiry — which may be partial. Stock enters the system only here.
7. Staff record sales. Price is resolved by the server. Stock is deducted
   soonest-expiry-first. The sale is marked paid, part-paid or on credit.
8. An invoice is generated and can be printed.
9. Unpaid sales appear on the Money Owed page, aged into buckets, largest debt first.
10. Payments are recorded against sales with a method and a mobile money reference until
    the balance clears.

## Features

### Catalogue
- Categories, brands and item groups — brands compete *within* an item group, which is
  what makes brand-versus-brand comparison possible
- Product variants with size, barcode, cost and sale price
- Unit-of-measure conversion: buy in cartons, stock and sell in singles
- Excel bulk upload with per-row validation
- Deactivation retires a product without destroying its trading history

### Purchasing
- Purchase orders with per-line quantity and cost, enterable in either unit
- Partial goods receipt with batch numbers and expiry dates
- Multi-supplier price comparison from order history — latest, best-ever, average,
  trend, and what switching supplier would save

### Sales
- Multi-line sales with server-resolved pricing
- FEFO stock deduction (first-expire-first-out)
- Discounts gated by permission and capped by a per-business ceiling
- Printable invoices

### Credit
- Sales marked paid, part-paid or on credit at the point of sale
- Payments with method (cash / mobile money / bank / cheque) and reference
- Ageing report bucketed current / 31–60 / 61–90 / over 90 days
- Printable per-customer statement with a running balance

### Administration
- IAM-style per-user permissions; roles are presets, not live bindings
- Activity log recording who changed what, with before and after values
- Per-tenant data export and restore
- Subscription plans with user and product limits, and feature gating

### Reporting
- Sales, purchases and stock reports with PDF, Excel and CSV export
- Dashboard with revenue trend, low-stock alerts and product counts

## Scope

### In Scope

- Multi-tenant inventory, purchasing, sales, credit and reporting for a single location
- Subscription plans and limit enforcement (payment collection is Stage 2B)
- Offline sale capture with sync on reconnect
- Progressive Web App — installable, no app store
- English only, Ghana Cedi only

### Out of Scope

- **Payment gateway integration** — planned for Stage 2B, deliberately not started.
  No Paystack code exists yet.
- **Customer-facing ordering portal** — wholesalers serve their customers directly
- **Multi-location / warehouse transfer** — only once a real customer has a second store;
  it touches every stock query, so it must not be speculative
- **GRA / VAT e-invoicing** — legally required for VAT-registered wholesalers, but
  deferred; revisit before pilot
- **Supplier ad placements or sponsored suggestions** — this directly contradicts the
  unbiased price comparison the product sells. You can have one or the other, not both.
- **Native mobile app (Capacitor)** — PWA covers the need; revisit only if pilot users
  cannot install it themselves
- **Per-tenant database schemas** — evaluated and rejected; row-level `business_id`
  scoping is already implemented and audited
- **Multi-currency, multi-language**

## Success Criteria

1. A brand-new business registers, adds a product, raises and receives a purchase order,
   records a sale, and views the invoice — without direct database access at any point.
2. `flask db upgrade` against a completely empty database produces a working, seeded
   application.
3. A Sales Staff account receives HTTP 403 on purchasing, suppliers, catalogue, staff
   management and backup, by direct URL — not merely a hidden nav link.
4. Neither staff role can see a cost price in the interface, in a CSV export, or by
   posting one by hand.
5. After any sequence of sales, voids and receipts, `flask reconcile-stock` reports no drift.
6. Business A's export contains no row belonging to Business B, verified against the
   decompressed archive.
7. The full test suite passes under bare `pytest` on the dependency versions CI resolves.
8. With the network disabled, the app loads, the catalogue is browsable, and a sale can be
   recorded and later synced exactly once.
