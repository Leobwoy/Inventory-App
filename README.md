# Inventory, Sales & Purchase Management System

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

### 🗄️ Database Backups & Portability
- **Backup & Restore Interface:** Built-in web utility to export a raw PostgreSQL binary dump or restore database tables via the UI.

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
├── products/          # Products blueprint, models, and routes
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
├── init_db.py         # Safe database table initializer
├── reset_db.py        # Database wipe-and-rebuild script
├── build.sh           # Deployment build script
├── render.yaml        # Render Infrastructure Blueprint
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

5. **Initialize Database Tables**:
   Create the tables without modifying existing data:
   ```bash
   python init_db.py
   ```
   *(Optionally, run `python reset_db.py` to wipe and recreate all tables.)*

6. **Run the Development Server**:
   ```bash
   python app.py
   ```
   The app will run locally at `http://127.0.0.1:5000/`.

---

## Deploying to Production (Render)

This application includes a native `render.yaml` configuration, allowing one-click deployment using Render Blueprints.

### Features Configured for Production:
1. **Automated Dialect Patching:** Render PostgreSQL connection URLs use `postgres://`, but SQLAlchemy 1.4+ requires `postgresql://`. The app automatically patches this on boot.
2. **Safe DB Building:** On every code push, `build.sh` runs `init_db.py` to dynamically add any new tables without affecting existing production data.
3. **Robust Connection Parameters:** Backup/Restore queries handle SSL and other connection flags (`?sslmode=require`) without regex failures.

### Steps to Deploy:
1. Push this repository to **GitHub**.
2. Go to your [Render Dashboard](https://render.com).
3. Click **New** -> **Blueprint**.
4. Link your GitHub repository.
5. Render will detect the `render.yaml` config and prompt you to create the database and the web service. Click **Apply**.
