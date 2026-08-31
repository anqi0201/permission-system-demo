"""
Schema design example: hierarchical ownership + audit-trail pattern.

This is a trimmed, illustrative excerpt showing the core design decisions
from a production CRM's schema — NOT the full schema, and all seed data
below is entirely fictional/placeholder. The two patterns worth noting:

1. Ownership model: every business-entity table carries a single
   `owner_id` referencing users(id). Combined with `manager_id` on the
   users table (self-referential), this is enough to derive a full
   visibility hierarchy at query time (see visibility.py) without
   duplicating org-chart data anywhere else.

2. Audit trail via table reuse: rather than building bespoke change-
   logging per module, one generic `activity_logs` table
   (entity_type + entity_id + actor + action + before/after JSON) is
   reused across every module. This was a deliberate reuse decision —
   the table already existed, unused, before the audit-trail feature
   was scoped.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'sales_rep',
    status TEXT NOT NULL DEFAULT 'active',
    perm_sales_data INTEGER DEFAULT 1,
    perm_logs INTEGER DEFAULT 0,
    manager_id INTEGER REFERENCES users(id),   -- self-referential hierarchy
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    country TEXT,
    region TEXT,
    type TEXT DEFAULT 'Distributor',
    level TEXT DEFAULT 'B',
    owner_id INTEGER REFERENCES users(id),     -- ownership/visibility scoping
    email TEXT,
    phone TEXT,
    annual_sales REAL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT UNIQUE NOT NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    order_date DATE NOT NULL,
    total_amount REAL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    status TEXT DEFAULT 'pending',
    owner_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Generic audit-trail table, reused across every module in the app
-- rather than building per-module change logs.
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,     -- e.g. 'order', 'customer', 'shipment'
    entity_id INTEGER,
    action TEXT,                   -- e.g. 'created', 'updated', 'stage_changed'
    description TEXT,
    changes TEXT,                  -- JSON: field-level before/after diff
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_customers_owner ON customers(owner_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_activity_logs_entity ON activity_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_users_manager ON users(manager_id);
"""


# --- Illustrative seed data (entirely fictional, for demo purposes only) ---

def seed_demo_data(conn):
    c = conn.cursor()

    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return

    # Fictional org chart: Admin -> Regional Manager -> Rep
    users = [
        ("admin", "Demo Administrator", "admin@example.com", "admin", None),
        ("regional_mgr", "Regional Sales Manager", "manager@example.com", "sales_manager", None),
        ("rep_1", "Sales Rep One", "rep1@example.com", "sales_rep", 2),  # manager_id -> regional_mgr
        ("rep_2", "Sales Rep Two", "rep2@example.com", "sales_rep", 2),
    ]
    for username, display_name, email, role, manager_id in users:
        c.execute(
            "INSERT INTO users (username, password_hash, display_name, email, role, manager_id) "
            "VALUES (?, 'placeholder_hash', ?, ?, ?, ?)",
            (username, display_name, email, role, manager_id),
        )
    conn.commit()

    customers = [
        ("Example Distributor Co.", "Germany", "Europe", "Distributor", "A", 3, 250000, "USD"),
        ("Sample Trading Group", "USA", "Americas", "Distributor", "B", 4, 180000, "USD"),
    ]
    for name, country, region, ctype, level, owner_id, annual_sales, currency in customers:
        c.execute(
            "INSERT INTO customers (name, country, region, type, level, owner_id, annual_sales, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, country, region, ctype, level, owner_id, annual_sales, currency),
        )
    conn.commit()

    print("Demo seed data inserted (fictional data, illustrative only).")
