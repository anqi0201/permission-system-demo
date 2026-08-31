# Hierarchical Permission System — Design Excerpt

This is a sanitized excerpt from a production internal CRM I designed and
built, showing the core access-control architecture. All company names,
employee names, domains, and business data have been replaced with
fictional placeholders — only the design patterns are real.

## What's here

- **`roles.py`** — single source of truth for a five-role hierarchy,
  including which roles can be assigned as whose manager.
- **`visibility.py`** — the core design piece: a recursive,
  ownership-based visibility model. A user can see/edit records they own
  plus everything owned by their subordinates (computed via a recursive
  SQL CTE walking a self-referential `manager_id` field), while a
  separate, deliberately distinct rule set governs *transferring*
  ownership of a record.
- **`auth.py`** — session-token authentication with FastAPI `Depends`-based
  route guards for both role checks and granular permission flags.
- **`schema_design_example.py`** — a trimmed schema showing the two core
  patterns: `owner_id` + `manager_id` for ownership/visibility, and one
  generic, reused `activity_logs` table for audit trails across every
  module instead of per-module logging.
- **`customer_health_scoring.py`** — the analytics layer: aggregates
  cross-module signals (pipeline, quotations, payments, recent activity
  sentiment) into a weighted 0-100 customer health score, a risk tier,
  and an auto-generated SWOT analysis.
- **`dashboard_aggregation.py`** — the BI/reporting layer: multi-dimensional
  SQL aggregation (by region, country, product category, sales rep, and
  month-over-month/year-over-year trend) that replaced manual
  spreadsheet cross-referencing with a live dashboard.

## Design decisions worth discussing in an interview

1. **Ownership vs. hierarchy are two different concerns.** Visibility
   ("can I see this record") is computed from the org tree. Transfer
   eligibility ("can I reassign this record, and to whom") is a
   separate rule set — conflating them was a bug I deliberately avoided.
2. **Table reuse over new schema.** The audit-log table already existed,
   unused, in the schema before the audit-trail feature was scoped —
   reusing it instead of adding new tables was a judgment call, not an
   accident.
3. **Recursive CTE over N+1 queries or app-level tree walking.** Visibility
   resolution happens in a single SQL query rather than recursive
   application code, which matters at any non-trivial team size.
4. **Rule-based scoring over a trained model, for now.** The customer
   health score is a hand-tuned weighted rule system rather than a
   trained model — a deliberate choice given the small customer base and
   the absence of labeled outcome data (e.g. "did this account actually
   churn") to train against. The aggregation step is designed so it could
   feed a trained model later without restructuring how the raw data is
   pulled.
5. **SQL aggregation over a dedicated ETL/OLAP pipeline.** The dashboard
   queries run directly against the live transactional tables. A
   separate reporting pipeline was evaluated and deliberately rejected —
   at this data volume and team size, it would have added a second
   system to maintain without a clear payoff.

## A known limitation, flagged honestly

`auth.py`'s `hash_password` uses unsalted SHA-256. This matches what
shipped in the original internal tool (a small, internal-only system with
a small user base), but it is **not** how I'd do password hashing for a
public-facing product — bcrypt/argon2 with per-user salts would be the
correct choice there. Worth being upfront about this if asked in an
interview rather than presenting the excerpt as flawless.
