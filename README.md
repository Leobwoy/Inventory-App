# TrackTrack - Wholesale Inventory, Sales & Purchase System

A premium, production-ready Flask web application for tracking products, managing suppliers, recording multi-item sales transactions, coordinating purchases, and visualizing real-time metrics. The frontend features a state-of-the-art **glassmorphic dark UI** with dynamic charts and responsive design, while the backend leverages **PostgreSQL** with strict transactional controls.

---

## Key Features

### 📊 Dynamic Dashboard & Real-Time Stats
- **Interactive Sales Charts:** Renders a 7-day rolling sales trend using Chart.js.
- **Clickable Metric Cards:** Instantly jump to detailed reports (e.g., clicking the "Low Stock" card navigates directly to the low-stock report).
- **Recent Activity Feed:** Real-time visibility into current inventory metrics.

### 📦 Product & Inventory Control
- **SKU/Name Search:** Fast, server-side lookup capability matching name fragments or SKUs.
- **Server-Side Pagination:** Optimized for high volume (15 records per page) to load thousands of records instantly without browser lag.
- **Low-Stock Alerts:** Automated visual badges highlighting items that have fallen below their customized safety stock thresholds.

### 💳 ACID Transactions (Sales & Purchases)
- **Multi-Item Checkout:** Record a sale containing multiple products simultaneously.
- **Atomicity & Consistency:** If any transaction step fails (e.g., product stock becomes insufficient halfway through check-out), the database session automatically rolls back (`db.session.rollback()`) to ensure no partial or corrupted records are created.
- **Inventory Autosync:** Stock levels automatically decrement upon sales and increment upon purchases, with smart handling during bulk deletes.

### 🗄️ Per-Tenant Backup & Portability
- **Owner-only export:** Downloads a ZIP of CSVs containing only *your* business's records — catalogue, suppliers, customers, purchase orders, stock batches and sales.
- **Scoped restore:** Imports back into your own business, remapping primary keys so an archive can never touch another business's data.

---

## Technology Stack

- **Backend:** Flask, Flask-SQLAlchemy (ORM), Flask-WTF (CSRF and Form Validation)
- **Database:** PostgreSQL (with `psycopg2-binary`)
- **Frontend:** Vanilla CSS (Glassmorphism), Bootstrap 5, Bootstrap Icons, Select2
- **Analytics & Reporting:** Chart.js, Pandas, openpyxl, reportlab, xlsxwriter
- **Production Server:** Gunicorn

---

## Directory Structure

```text
├── auth/              # Business, User, Role, Permission, AuditLog + login/registration
├── products/          # Products, categories, brands, item groups, suppliers
├── sales/             # Sales transactions, customers, and routes
├── purchases/         # Purchases from suppliers and routes
├── reports/           # Business metrics, charts, and exports
├── static/
│   ├── css/style.css  # Custom CSS system (dark variables, glassmorphic layout)
│   └── logo.png       # Application brand image
├── templates/         # Jinja2 HTML templates
│   ├── base.html      # Sidebar template with RBAC role views
│   └── _macros.html   # Reusable pagination controls
├── app.py             # Main application entry point & factory
├── extensions.py      # Flask extension instances
├── services/          # Service layer (backup/export, stock rules)
├── reset_db.py        # Database wipe-and-rebuild script
├── seed_db.py         # Database seeder (wholesale business datasets)
├── build.sh           # Build script (runs flask db upgrade)
├── Dockerfile         # Container image for Koyeb
├── migrations/        # Alembic migration chain (the only way to build schema)
└── requirements.txt   # Python package dependencies
```

---

## Local Development Setup

### 1. Prerequisites
- **Python 3.8+** installed.
- **PostgreSQL** installed and running locally.

### 2. Installation Steps
1. **Clone the Repository** and navigate to the project directory:
   ```bash
   git clone <your-repo-url>
   cd "Sales&Purchase"
   ```

2. **Set Up a Virtual Environment** (recommended):
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Database Configuration**:
   Create a local PostgreSQL database named `purchasesalesdb`. The app defaults to connecting via:
   `postgresql://postgres:postgres123@localhost:5432/purchasesalesdb`
   
   If you have a different PostgreSQL user, password, or host, set the `DATABASE_URL` environment variable:
   ```bash
   # Windows (PowerShell)
   $env:DATABASE_URL="postgresql://username:password@localhost:5432/databasename"
   
   # Linux/macOS
   export DATABASE_URL="postgresql://username:password@localhost:5432/databasename"
   ```

5. **Build the Database**:
   Tables, roles and permissions all come from migrations. Do not use
   `db.create_all()` — it produces tables with no seed data, and registration
   then fails with "Owner role not found".
   ```bash
   flask db upgrade
   ```
   To wipe and rebuild a local database from scratch:
   ```bash
   python reset_db.py
   ```
   To load a realistic demo dataset (Ghanaian beverage wholesaler — brands,
   variants, suppliers, purchase orders, goods receipts and sales):
   ```bash
   python seed_db.py
   ```

6. **Run the Development Server**:
   ```bash
   python app.py
   ```
   The app runs at `http://127.0.0.1:5000/`. Register a business to begin — the
   first account becomes the Owner.

---

## Deploying to Production (Koyeb + Neon)

Both tiers are free with no expiry clock. **Do not use Render's free
PostgreSQL**: it is deleted 30 days after creation (plus a 14-day grace period)
and supports no backups. AWS is not a viable free option either — its
always-free tier includes no PostgreSQL and no persistent server, and new
accounts close automatically after six months.

### 1. Database — Neon
1. Create a project at [neon.tech](https://neon.tech), region **Frankfurt**
   (better latency to Ghana than US regions; West African cables route north to
   Europe).
2. Copy the connection string. It already uses the `postgresql://` prefix.

### 2. App — Koyeb
1. Create a service at [koyeb.com](https://koyeb.com) from this GitHub repo,
   region **Frankfurt**. It builds from the included `Dockerfile`.
2. Set these as **secrets**:
   - `DATABASE_URL` — the Neon connection string
   - `SECRET_KEY` — a long random value (`python -c "import secrets; print(secrets.token_hex(32))"`)
3. Deploy. The container runs `flask db upgrade` on start, so the schema, roles
   and permissions are built automatically.

### Notes
- The free Koyeb instance scales to zero after 1 hour idle; the next request
  incurs a cold start of a few seconds. This cannot be disabled on the free tier.
- Render URLs use the `postgres://` prefix, which SQLAlchemy rejects; `app.py`
  still patches this on boot, so a Render database would also work if needed.
- When a pilot needs no cold starts at all, graduate to an **Oracle Cloud Always
  Free** ARM VM (4 cores / 24 GB / 200 GB, never sleeps) running Postgres
  locally with `pg_dump` backups to free Object Storage.
