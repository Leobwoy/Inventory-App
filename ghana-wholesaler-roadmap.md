# Product Roadmap & Technical Spec: Ghanaian Wholesaler Inventory & Supplier Platform

**Strategic positioning:** The deepest supplier and inventory management tool built for Ghanaian wholesalers — not a payments hub, not a customer marketplace. Payments (MoMo) and customer-facing ordering are deliberately deferred to a later phase so the product can be excellent at one thing first.

**Current codebase state (verified, July 2026):** Flask + PostgreSQL. Products/Categories/Suppliers/Customers CRUD, multi-item Sales with invoicing, Purchases (instant receipt — no PO status), Reports (PDF/Excel/CSV export), DB backup/restore. **No authentication, no multi-tenancy, no roles, no batch/expiry tracking, no product variant structure.**

---

## Phase -1 — Foundation & Security
*Nothing in later phases is safe to build until this phase is done — later features depend on this schema.*

### 1. Multi-tenancy
- New `Business` table: `id, name, created_at`
- Add `business_id` FK to every existing table: `Product, Category, Supplier, Customer, Sale, Purchase`
- All queries must be scoped by `business_id` — this is the single most important rule for the whole codebase going forward. Every route handler needs a tenant filter, not just a login check.

### 2. Authentication + RBAC (real IAM, not just a login page)
**Tables:**
- `User`: `id, business_id (FK), name, email (unique per business), password_hash, role_id (FK), is_active, created_at, last_login_at`
- `Role`: `id, name, is_system_role (bool)` — seed with: **Owner**, **Manager**, **Inventory Staff**, **Sales Staff**, **Viewer**
- `Permission`: `id, code (e.g. 'products.create', 'purchase_orders.approve', 'users.manage', 'backup.run'), description`
- `RolePermission`: `role_id, permission_id` (many-to-many)

**Permission matrix (seed data for the 5 default roles):**

| Module / Action | Owner | Manager | Inventory Staff | Sales Staff | Viewer |
|---|---|---|---|---|---|
| Products — view | Y | Y | Y | Y | Y |
| Products — create/edit | Y | Y | Y | N | N |
| Products — delete | Y | Y | N | N | N |
| **Cost price / margin — view** | Y | Y | N | N | N |
| Suppliers — view/manage | Y | Y | Y | N | N |
| Purchase Orders — create | Y | Y | Y | N | N |
| Purchase Orders — approve | Y | Y | N | N | N |
| Goods receipt (mark received) | Y | Y | Y | N | N |
| Sales — create | Y | Y | N | Y | N |
| Sales — void/delete | Y | Y | N | N | N |
| Customers — view/manage | Y | Y | N | Y | N |
| Reports — view | Y | Y | Y | Y | Y |
| Reports — export | Y | Y | Y | N | N |
| **Backup / restore database** | Y | N | N | N | N |
| **User management (create/edit/revoke/delete users)** | Y | N | N | N | N |
| Audit log — view | Y | Y | N | N | N |

Notes for the agent:
- **Cost price / margin visibility is a real business requirement, not a nice-to-have** — Ghanaian wholesale owners routinely don't want floor staff seeing what they paid vs. what they charge. `Product.cost_price` (see Phase 1 schema below) must be hidden from Sales/Inventory Staff and Viewer roles at the API/template level, not just hidden in the UI.
- **Backup/restore is currently a live security hole** — `/backup_restore` has no auth check at all right now, and it can drop and recreate the entire database. This must be locked to Owner-only immediately, before multi-tenancy even ships, or one tenant could wipe another's data.
- Ship fixed roles first (table above). A "custom role builder" UI (checkbox grid over the `Permission` table) can come later — the `RolePermission` model already supports it, so don't hardcode role checks in route logic; check permissions, not role names.

### 3. User Management UI (new admin-only tab)
- List all users in the business, with role, status (active/suspended), last login
- Create user (name, email, temp password or invite-by-email), assign role
- Edit user (change role, reset password)
- Suspend/revoke (deactivate `is_active`, don't hard-delete — preserves audit trail integrity)
- Delete user (only if they have no historical records tied to them, otherwise force suspend instead)

### 4. Audit Log
- `AuditLog`: `id, business_id, user_id, action, entity_type, entity_id, timestamp, details_json`
- Log at minimum: stock adjustments, price changes, PO approvals, sale voids, user role changes, backup/restore actions
- This matters as soon as more than one person has write access — it's your only way to answer "who changed this price" later

### 5. Product hierarchy restructuring (brand + variant/size model)
Right now `Product` is a flat single-SKU row. To support "BelAqua vs Verna, each in Large/Medium/Small" as a reportable structure:

- `Brand`: `id, business_id, name` (BelAqua, Verna, U-Fresh, Coca-Cola, etc.)
- `ItemGroup`: `id, business_id, name, category_id (FK)` — the generic item concept that brands compete within (e.g. "Bottled Water", "Soya Drink") — this is what lets you compare BelAqua vs. Verna as substitutes
- `Product` (this becomes the actual sellable variant/SKU row): `id, business_id, item_group_id (FK), brand_id (FK), variant_label (e.g. "750ml", "1.5L", "Large"), size_value (numeric, e.g. 750), size_unit (ml/L/kg/g/pcs), sku (unique per business), barcode (nullable), cost_price, unit_price, quantity_in_stock, min_stock_alert, is_active`

Example resulting rows:
| ItemGroup | Brand | Product (variant) |
|---|---|---|
| Bottled Water | BelAqua | BelAqua 750ml |
| Bottled Water | BelAqua | BelAqua 1.5L |
| Bottled Water | Verna | Verna 750ml |
| Soya Drink | U-Fresh | U-Fresh Soya 500ml |

This is separate from **unit-of-measure conversion** (below) — variant/size is about *which product* ("BelAqua 750ml" is a different SKU from "BelAqua 1.5L"), while UoM conversion is about *how one SKU is bought/sold* (a carton of BelAqua 750ml contains 24 pieces). Don't conflate the two in the schema.

### 6. PO status lifecycle
Currently `add_purchase()` increases stock the instant a purchase is logged — no order/receiving distinction. Replace with:

- `PurchaseOrder`: `id, business_id, supplier_id, status (enum: draft, ordered, partially_received, received, cancelled), order_date, expected_date, created_by (FK User), approved_by (FK User, nullable)`
- `PurchaseOrderItem`: `id, po_id, product_id, quantity_ordered, quantity_received (default 0), unit_cost`
- Stock only increments when a **goods receipt** is recorded against a PO item, not when the PO is created — this is what makes partial receiving and the expiry/batch tracking below possible.
- "Paid" status is deliberately **not** part of this enum yet — payment status tracking without a gateway is a manual field, save for Phase 2's credit ledger work, don't build it prematurely here.

---

## Phase 1 — Differentiation (supplier + inventory depth — this is where you win)

### 1. Batch/expiry tracking + alerts
- `StockBatch`: `id, product_id (FK), po_item_id (FK, nullable), batch_number, quantity_received, quantity_remaining, received_date, expiry_date (nullable — not every item expires)`
- Every goods receipt creates a `StockBatch` row rather than just incrementing `Product.quantity_in_stock` directly — `Product.quantity_in_stock` becomes a derived sum of `StockBatch.quantity_remaining` (or kept in sync via a service function, agent's choice, but must stay consistent)
- **Expiry alerts**: scheduled check (daily) flags batches where `expiry_date <= today + N days` (N configurable per business, default 30). Surface these on the dashboard alongside the existing low-stock alert — same visual pattern, new alert type.
- **FEFO (first-expire-first-out)**: when a sale is recorded, deduct from the batch with the soonest `expiry_date` first, not just any batch. This is the kind of detail that makes the product feel genuinely built for people who move perishable/dated stock, not a generic inventory template.

### 2. Supplier performance scorecards
Computed from existing + new data — no need for a dedicated table at first, build as queries/views:
- On-time delivery %: compare `PurchaseOrder.expected_date` vs. actual goods-receipt date
- Price consistency: track `unit_cost` per product per supplier over time, flag variance
- Fulfillment accuracy: `quantity_received` vs `quantity_ordered` ratio per PO
- Surface as a per-supplier scorecard page and as a ranking when choosing a supplier for reorder

### 3. Multi-supplier price comparison
- When creating a new PO or viewing a product, show historical `unit_cost` for that product/variant across all suppliers who've supplied it, sorted by best recent price and reliability
- This is the single clearest "nobody else in this market has this" feature — it directly uses the `Product`/`Brand`/`ItemGroup` restructuring plus PO history

### 4. Multi-unit-of-measure (UoM) conversion
- `Product` gains: `base_uom (e.g. 'piece')`, `purchase_uom (e.g. 'carton')`, `units_per_purchase_uom (e.g. 24)`
- Purchases are entered in purchase UoM (cartons), sales/stock tracked in base UoM (pieces) — conversion happens automatically at entry
- This is a hard requirement for wholesale and currently missing entirely

### 5. Smart reorder alerts
- Extend the existing low-stock check to factor in average supplier lead time (from scorecard data) — "reorder now" should mean "you'll run out before a new order can arrive," not just "you're under the static threshold"

---

## Phase 2 — Parity (only after Phase 1 is proven with real users)
- Multi-location/warehouse support with stock transfer
- Manual credit/debtor ledger — record what a customer owes and partial payments **without** a payment gateway attached (just bookkeeping, no MoMo yet)
- Deeper reporting (profit margins by brand/item group, supplier spend analysis)

## Phase 3 — Expansion (deliberately distant)
- MoMo/Paystack payment gateway integration
- Customer-facing self-service ordering portal
- Supplier ad placements / sponsored suggestions
- GRA/VAT compliance tooling

---

## Other things worth flagging (not yet raised, but matter)

1. **Backup/restore has no access control today** — flagged above in Phase -1, but worth repeating as the single most urgent fix given it can currently drop the database with zero authentication.
2. **Database migrations**: the codebase has no visible Alembic/Flask-Migrate setup. Once multiple people (and eventually multiple tenants) depend on this schema, ad-hoc schema changes become dangerous. Set up Flask-Migrate now, before Phase -1 changes land, so every schema change from here on is a reviewable, reversible migration.
3. **SKU/barcode uniqueness**: once variants exist, SKU generation should follow a predictable pattern (e.g. `{business}-{itemgroup}-{brand}-{size}`) to avoid collisions and make bulk product upload (the existing `upload_products` route) still work sensibly with variants.
4. **Password/session security basics**: password hashing (use `werkzeug.security` or `bcrypt`, not homegrown), session timeout, and a "force password reset" flow for the User Management tab — small but easy to get wrong.
5. **Ghana Data Protection Act (Act 843)**: you'll be storing customer and supplier personal data (phone, address). Worth a basic data-handling review before wider rollout — not urgent for MVP, but flag it now so it's not forgotten later.
6. **Notification center**: as you add expiry alerts to the existing low-stock alerts, consider a unified alerts/notifications view (with severity and dismiss/resolve state) rather than two separate ad-hoc dashboard widgets — this scales better as you add more alert types later (e.g. supplier price spikes).

---

## Migration Sequence (Flask-Migrate / Alembic)

The codebase has no migrations yet, and there's already live data on Render — so the first rule is: **every migration that adds a required field must land in three steps, not one** — (1) add the column nullable, (2) backfill existing rows in the same migration or a data-migration script, (3) enforce NOT NULL in a follow-up migration once backfill is confirmed. Never ship a single migration that adds a NOT NULL column with no default against a table that already has rows — it will fail on deploy.

Before starting: **use the backup/restore feature to snapshot the current production DB**, and test the full migration sequence against a restored copy locally before ever running it on Render. Lock down `/backup_restore` (Phase -1, item 2) before doing anything else — do this as a hotfix ahead of the sequence below, independent of migration numbering.

| # | Migration | What it does | Backfill needed? |
|---|---|---|---|
| 0001 | `baseline` | `flask db init` + autogenerate a snapshot of the current schema (Product, Category, Supplier, Customer, Sale, SaleItem, Purchase). No structural change — this just gives Alembic a starting point to diff against. | No |
| 0002 | `add_business_table` | Create `Business` table. Insert one row representing the existing store (e.g. name = your actual business name) — this becomes the tenant all current data belongs to. | No |
| 0003 | `add_business_id_fk` | Add `business_id` (nullable FK) to `Product, Category, Supplier, Customer, Sale, Purchase`. | **Yes** — set every existing row's `business_id` to the Business row created in 0002. |
| 0004 | `enforce_business_id_not_null` | Alter all `business_id` columns to NOT NULL now that backfill is confirmed. | No (relies on 0003) |
| 0005 | `add_rbac_tables` | Create `Role`, `Permission`, `RolePermission`. Seed the 5 default roles and the permission matrix from Phase -1 as data in this migration. | Seed data, not backfill |
| 0006 | `add_user_table` | Create `User` table (`business_id`, `role_id` FKs). Do **not** hardcode a default password in the migration — instead add a one-time setup route/CLI command (`flask create-owner`) that prompts for the first Owner account per business. | No — handled by setup command, not migration |
| — | *(code milestone, not a migration)* | Wire `login_required` + permission checks onto every existing route, including `/backup_restore`. This must land in the same deploy as 0006 — having a User table without enforcement is a false sense of security. | — |
| 0007 | `add_audit_log` | Create `AuditLog` table. | No |
| 0008 | `add_brand_and_itemgroup` | Create `Brand`, `ItemGroup` tables (`business_id` scoped). Seed one fallback `ItemGroup` ("Uncategorized") and one fallback `Brand` ("Generic") per existing business. | No structural backfill yet — used in 0009 |
| 0009 | `restructure_product_variants` | Add nullable columns to `Product`: `item_group_id, brand_id, variant_label, size_value, size_unit, cost_price, base_uom, purchase_uom, units_per_purchase_uom`. | **Yes** — assign every existing `Product` row to the "Uncategorized"/"Generic" fallbacks from 0008, set `variant_label` from the existing product name, set `base_uom = 'piece'` and `units_per_purchase_uom = 1` as safe defaults. |
| 0010 | `enforce_product_variant_not_null` | Once backfill in 0009 is confirmed correct, enforce NOT NULL on `item_group_id, brand_id, base_uom`. Leave `cost_price`, `size_value`, `size_unit` nullable — not every product needs them immediately, and forcing data entry on every existing row before launch will stall the rollout. | No |
| 0011 | `add_purchase_order_tables` | Create `PurchaseOrder`, `PurchaseOrderItem`. | **Yes** — write a data-migration script converting every existing `Purchase` row into a `PurchaseOrder` (status = `received`, since stock was already incremented) + one `PurchaseOrderItem`. Keep the old `Purchase` table in place, unused, for one release cycle as a rollback safety net — don't drop it in this migration. |
| 0012 | `add_stock_batch` | Create `StockBatch` table. | **Yes** — for every `Product`, create one `StockBatch` row with `quantity_remaining = Product.quantity_in_stock`, `expiry_date = NULL`, `received_date = Product creation date (or today if unavailable)`. |
| — | *(code milestone, not a migration)* | Switch stock read/write logic to sum from `StockBatch.quantity_remaining` instead of writing `Product.quantity_in_stock` directly, and implement FEFO deduction on sale. Land this in the same release as 0012 — a `StockBatch` table that the app doesn't actually use yet just creates two sources of truth. | — |
| 0013 | `add_expiry_alert_config` | Add `expiry_alert_days` (default 30) to `Business` table so the alert threshold is configurable per tenant. | No |
| 0014 (Phase 2) | `add_credit_ledger` | Create manual `CreditLedger`/`Payment` tables (no gateway fields yet — just `amount, method (cash/momo-manual/bank), recorded_by, date, notes`). | No |
| 0015 (Phase 2) | `add_locations` | Multi-location/warehouse support, if pursued. | Depends on scope at the time |

**Deploy discipline for each numbered migration above:** run it against a local restore of the production backup first, verify row counts and spot-check a few records post-backfill, then deploy to Render during low-traffic hours. Migrations with a "Yes" backfill are the risky ones — treat 0003, 0009, and 0011–0012 as their own deploys, not bundled with unrelated code changes, so a problem is easy to isolate and roll back.

