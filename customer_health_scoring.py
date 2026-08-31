"""
Customer health-scoring engine: aggregates cross-module activity into a
single health score, SWOT analysis, and risk tier for each customer.

This is the analytics-layer counterpart to the permission-system design
in visibility.py / roles.py — same project, different concern: turning
raw transactional data (opportunities, quotations, orders, payments,
activity logs) into a business-readable signal a sales manager can act
on without manually cross-referencing five different modules.

Design notes worth discussing in an interview:

1. The health score is a hand-tuned weighted rule system, not a trained
   model — deliberately so. With a small customer base and no labeled
   "churned vs. retained" outcome data yet, a rule-based score is more
   interpretable, easier to sanity-check with the sales team, and easier
   to adjust when a rule proves wrong. It's designed to be replaced by
   a trained model later, once there's enough labeled history to make
   that worthwhile — the aggregation step (_aggregate_customer_metrics)
   is exactly the feature set a future model would consume.
2. Scoring, SWOT generation, and recommendation text are three separate
   functions operating on the same metrics dict, so any one of them can
   be swapped independently (e.g. replacing the scoring function with a
   trained model later touches nothing else downstream).
"""
from datetime import date, timedelta
from typing import List


def aggregate_customer_metrics(conn, customer_id: int) -> dict:
    """Pull and aggregate everything relevant to one customer's health:
    pipeline, quotations, orders/payments, recent activity, and samples.
    Returns a flat metrics dict consumed by scoring + SWOT generation.
    """
    # Pipeline
    opps = conn.execute(
        """SELECT stage, amount, currency, expected_close_date, created_at
           FROM opportunities WHERE customer_id = ?""",
        (customer_id,),
    ).fetchall()
    active_opps = [o for o in opps if o["stage"] not in ("completed", "lost")]
    won_opps = [o for o in opps if o["stage"] == "completed"]
    lost_opps = [o for o in opps if o["stage"] == "lost"]
    pipeline_value = sum(o["amount"] or 0 for o in active_opps)
    won_value = sum(o["amount"] or 0 for o in won_opps)

    # Quotations
    quotes = conn.execute(
        """SELECT status, total_amount, currency, created_at, validity_date
           FROM quotations WHERE customer_id = ? ORDER BY created_at DESC""",
        (customer_id,),
    ).fetchall()
    pending_quotes = [q for q in quotes if q["status"] in ("draft", "sent")]
    accepted_quotes = [q for q in quotes if q["status"] == "accepted"]

    # Orders + payments (overdue detection)
    orders = conn.execute(
        "SELECT id, total_amount, currency, status, order_date FROM orders WHERE customer_id = ?",
        (customer_id,),
    ).fetchall()
    order_ids = [o["id"] for o in orders]
    payments = []
    if order_ids:
        placeholders = ",".join("?" * len(order_ids))
        payments = conn.execute(
            f"SELECT * FROM payments WHERE order_id IN ({placeholders})", order_ids
        ).fetchall()
    overdue_payments = [
        p for p in payments
        if p["status"] == "pending" and p["due_date"] and p["due_date"] < date.today().isoformat()
    ]
    paid_amount = sum((p["amount"] or 0) for p in payments if p["status"] == "paid")

    # Recent engagement (last 90 days of activity logs)
    cutoff = (date.today() - timedelta(days=90)).isoformat()
    logs = conn.execute(
        """SELECT activity_type, mood, ai_score, log_date FROM sales_logs
           WHERE customer_id = ? AND log_date >= ? ORDER BY log_date DESC""",
        (customer_id, cutoff),
    ).fetchall()
    avg_mood_score = sum((l["ai_score"] or 50) for l in logs) / max(len(logs), 1)
    days_since_last_contact = None
    if logs:
        try:
            last_date = date.fromisoformat(logs[0]["log_date"])
            days_since_last_contact = (date.today() - last_date).days
        except Exception:
            pass

    # Samples in flight
    samples = conn.execute(
        "SELECT status FROM samples WHERE customer_id = ?", (customer_id,)
    ).fetchall()
    active_samples = [s for s in samples if s["status"] in ("requested", "preparing", "shipped", "received")]

    return {
        "active_opps": len(active_opps),
        "won_opps": len(won_opps),
        "lost_opps": len(lost_opps),
        "pipeline_value": pipeline_value,
        "won_value": won_value,
        "pending_quotes": len(pending_quotes),
        "accepted_quotes": len(accepted_quotes),
        "orders": len(orders),
        "paid_amount": paid_amount,
        "overdue_payments": len(overdue_payments),
        "recent_logs": len(logs),
        "avg_mood_score": round(avg_mood_score, 1),
        "days_since_last_contact": days_since_last_contact,
        "active_samples": len(active_samples),
    }


def calculate_health_score(metrics: dict) -> int:
    """Weighted rule-based health score, 0-100. Starts from a neutral
    baseline of 50 and adjusts based on pipeline contribution, engagement
    recency/frequency, sentiment, and payment health."""
    score = 50

    # Pipeline contribution
    score += min(metrics["active_opps"] * 4, 15)
    score += min(metrics["accepted_quotes"] * 5, 10)
    score += min(metrics["pending_quotes"] * 2, 6)

    # Engagement frequency
    if metrics["recent_logs"] >= 5:
        score += 8
    elif metrics["recent_logs"] >= 2:
        score += 4
    elif metrics["recent_logs"] == 0:
        score -= 10

    # Engagement recency
    if metrics["days_since_last_contact"] is not None:
        if metrics["days_since_last_contact"] > 60:
            score -= 12
        elif metrics["days_since_last_contact"] > 30:
            score -= 6
        elif metrics["days_since_last_contact"] <= 7:
            score += 5

    # Sentiment (derived from logged interaction mood scores)
    if metrics["avg_mood_score"] >= 80:
        score += 8
    elif metrics["avg_mood_score"] >= 65:
        score += 4
    elif metrics["avg_mood_score"] < 40:
        score -= 8

    # Payment health
    if metrics["overdue_payments"] == 0 and metrics["orders"] > 0:
        score += 6
    if metrics["overdue_payments"] > 0:
        score -= min(metrics["overdue_payments"] * 4, 12)

    # Historical wins
    score += min(metrics["won_opps"] * 5, 10)

    return max(0, min(100, score))


def risk_level(score: int) -> str:
    if score >= 75:
        return "low"
    if score >= 55:
        return "medium"
    if score >= 35:
        return "high"
    return "critical"


def generate_swot(metrics: dict) -> dict:
    """Rule-based SWOT generation from the same metrics dict used for
    scoring — deliberately kept as a separate function so the scoring
    logic and the narrative-generation logic can evolve independently."""
    strengths: List[str] = []
    weaknesses: List[str] = []
    opportunities: List[str] = []
    threats: List[str] = []

    if metrics["active_opps"] >= 2:
        strengths.append(f"Tracking {metrics['active_opps']} active opportunities — healthy pipeline")
    if metrics["won_value"] > 50000:
        strengths.append(f"${metrics['won_value']:,.0f} in historical closed deals")
    if metrics["avg_mood_score"] >= 70:
        strengths.append("Recent customer interactions have been positive")
    if metrics["days_since_last_contact"] is not None and metrics["days_since_last_contact"] <= 14:
        strengths.append("Consistent engagement within the last two weeks")
    if metrics["accepted_quotes"] >= 1:
        strengths.append("Has an accepted quotation")

    if metrics["avg_mood_score"] < 50:
        weaknesses.append("Recent interactions have skewed negative")
    if metrics["days_since_last_contact"] is not None and metrics["days_since_last_contact"] > 30:
        weaknesses.append(f"No contact in {metrics['days_since_last_contact']} days")
    if metrics["overdue_payments"] > 0:
        weaknesses.append(f"{metrics['overdue_payments']} overdue payment(s)")
    if metrics["lost_opps"] > metrics["won_opps"]:
        weaknesses.append("Lost opportunities exceed wins")

    if metrics["pending_quotes"] >= 1:
        opportunities.append(f"{metrics['pending_quotes']} quotation(s) awaiting follow-up")
    if metrics["active_samples"] >= 1:
        opportunities.append("Samples in transit can drive conversion")
    if metrics["active_opps"] >= 1:
        opportunities.append("Active opportunities have room to advance stage")

    if metrics["overdue_payments"] > 0:
        threats.append("Overdue payments are eroding trust")
    if metrics["days_since_last_contact"] is not None and metrics["days_since_last_contact"] > 60:
        threats.append("Customer may be drifting toward a competitor")
    if metrics["lost_opps"] >= 2:
        threats.append("High historical loss rate — review root causes")

    if not strengths:
        strengths.append("No clear strengths yet — look for an opening to build one")
    if not weaknesses:
        weaknesses.append("No significant weaknesses")
    if not opportunities:
        opportunities.append("Proactively look for a new entry point")
    if not threats:
        threats.append("No significant external threats")

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "opportunities": opportunities,
        "threats": threats,
    }
