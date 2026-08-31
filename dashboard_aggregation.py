"""
Dashboard aggregation queries: the reporting layer that replaced manual
Excel cross-referencing with live, multi-dimensional views over the same
transactional tables everyone else in the app writes to.

Design note: this deliberately uses direct SQL aggregation against the
live OLTP tables rather than a separate ETL/OLAP pipeline. At this data
volume and team size, a dedicated pipeline would have added real
maintenance overhead (a second system to keep in sync, monitor, and
debug) without a corresponding benefit — these queries run comfortably
fast against the existing tables and indexes. This was a deliberate
right-sizing decision, not an oversight; the schema's indexes
(see schema_design_example.py) were chosen partly with these queries
in mind.
"""
from fastapi import APIRouter, Depends
from datetime import datetime
from .database import get_db
from .auth import get_current_user

router = APIRouter()


@router.get("/dashboard")
def get_dashboard(user=Depends(get_current_user)):
    conn = get_db()

    # Customer distribution
    total_customers = conn.execute("SELECT COUNT(*) FROM customers WHERE status = 'active'").fetchone()[0]
    customers_by_region = {}
    for r in conn.execute(
        "SELECT region, COUNT(*) as cnt FROM customers WHERE region IS NOT NULL GROUP BY region"
    ).fetchall():
        customers_by_region[r["region"]] = r["cnt"]

    # Pipeline overview
    total_opps = conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE stage NOT IN ('completed', 'lost')"
    ).fetchone()[0]
    pipeline_value = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM opportunities WHERE stage NOT IN ('completed', 'lost')"
    ).fetchone()[0]

    # Pipeline by funnel stage
    stages = ["lead", "qualified", "sample", "quotation", "negotiation", "po", "completed", "lost"]
    pipeline_by_stage = {}
    for stage in stages:
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as total FROM opportunities WHERE stage = ?",
            (stage,),
        ).fetchone()
        pipeline_by_stage[stage] = {"count": row["cnt"], "value": row["total"]}

    # Year-to-date wins
    won_value = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM opportunities "
        "WHERE stage = 'completed' AND strftime('%Y', updated_at) = strftime('%Y', 'now')"
    ).fetchone()[0]
    won_count = conn.execute(
        "SELECT COUNT(*) FROM opportunities "
        "WHERE stage = 'completed' AND strftime('%Y', updated_at) = strftime('%Y', 'now')"
    ).fetchone()[0]

    # Quotation funnel
    total_quotations = conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]
    pending_quotations = conn.execute("SELECT COUNT(*) FROM quotations WHERE status = 'sent'").fetchone()[0]
    accepted_quotations = conn.execute("SELECT COUNT(*) FROM quotations WHERE status = 'accepted'").fetchone()[0]

    # Sales by country (top 10 by closed value)
    sales_by_country = []
    for r in conn.execute(
        """SELECT cu.country, COUNT(*) as cnt, COALESCE(SUM(o.amount), 0) as total
           FROM opportunities o
           JOIN customers cu ON o.customer_id = cu.id
           WHERE o.stage = 'completed' AND cu.country IS NOT NULL
           GROUP BY cu.country
           ORDER BY total DESC
           LIMIT 10"""
    ).fetchall():
        sales_by_country.append({"country": r["country"], "count": r["cnt"], "value": r["total"]})

    # Sales by product category
    sales_by_category = []
    for r in conn.execute(
        """SELECT p.category, COUNT(*) as cnt, COALESCE(SUM(o.amount), 0) as total
           FROM opportunities o
           LEFT JOIN products p ON o.product_id = p.id
           WHERE p.category IS NOT NULL
           GROUP BY p.category
           ORDER BY total DESC"""
    ).fetchall():
        sales_by_category.append({"category": r["category"], "count": r["cnt"], "value": r["total"]})

    # Rep-level performance (this is the view that replaced manually
    # cross-referencing individual reps' Excel submissions)
    sales_by_owner = []
    for r in conn.execute(
        """SELECT u.display_name, COUNT(*) as cnt, COALESCE(SUM(o.amount), 0) as total
           FROM opportunities o
           JOIN users u ON o.owner_id = u.id
           WHERE o.stage NOT IN ('lost')
           GROUP BY u.display_name
           ORDER BY total DESC"""
    ).fetchall():
        sales_by_owner.append({"name": r["display_name"], "count": r["cnt"], "value": r["total"]})

    # Recent activity feed
    recent_opps = []
    for r in conn.execute(
        """SELECT o.*, cu.name as customer_name, u.display_name as owner_name
           FROM opportunities o
           LEFT JOIN customers cu ON o.customer_id = cu.id
           LEFT JOIN users u ON o.owner_id = u.id
           ORDER BY o.updated_at DESC
           LIMIT 5"""
    ).fetchall():
        recent_opps.append(dict(r))

    return {
        "total_customers": total_customers,
        "customers_by_region": customers_by_region,
        "active_opportunities": total_opps,
        "pipeline_value": pipeline_value,
        "pipeline_by_stage": pipeline_by_stage,
        "won_value": won_value,
        "won_count": won_count,
        "total_quotations": total_quotations,
        "pending_quotations": pending_quotations,
        "accepted_quotations": accepted_quotations,
        "sales_by_country": sales_by_country,
        "sales_by_category": sales_by_category,
        "sales_by_owner": sales_by_owner,
        "recent_opportunities": recent_opps,
        "monthly_comparison": _monthly_comparison(conn),
    }


def _monthly_comparison(conn):
    """Month-by-month revenue, current year vs. prior year — the classic
    YoY comparison view. Returns month numbers (1-12), not localized
    labels; the frontend decides display formatting, keeping the API
    layer free of locale/language concerns."""
    year = datetime.now().year
    result = {"months": list(range(1, 13)), "this_year": [], "last_year": [], "this_month": 0, "last_month": 0}
    for m in range(1, 13):
        t = conn.execute(
            "SELECT COALESCE(SUM(total_amount),0) as v FROM orders "
            "WHERE status='completed' AND strftime('%Y',order_date)=? AND strftime('%m',order_date)=?",
            (str(year), f"{m:02d}"),
        ).fetchone()["v"]
        l = conn.execute(
            "SELECT COALESCE(SUM(total_amount),0) as v FROM orders "
            "WHERE status='completed' AND strftime('%Y',order_date)=? AND strftime('%m',order_date)=?",
            (str(year - 1), f"{m:02d}"),
        ).fetchone()["v"]
        result["this_year"].append(round(t / 1000, 1))
        result["last_year"].append(round(l / 1000, 1))
    nm = datetime.now().month
    result["this_month"] = result["this_year"][nm - 1] if nm > 0 else 0
    result["last_month"] = result["this_year"][nm - 2] if nm > 1 else result["last_year"][11]
    return result
