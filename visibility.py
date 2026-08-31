"""
Core visibility-scoping logic for a hierarchical, ownership-based
permission model.

Core idea: a user can view/edit a record = records they own, plus all
records owned by anyone recursively below them in the org tree
(see can_manage_owner()).

A second, independent rule set governs *transferring* record ownership
(can_initiate_transfer / is_eligible_transfer_recipient). This is
deliberately NOT the same rule as can_manage_owner:
  - Initiating a transfer does not require the current owner to fall
    within the initiator's visibility scope — the owner themself, or
    anyone at manager level or above, can initiate.
  - Eligibility to *receive* a transferred record is restricted to
    sales-line roles, independent of the initiator's own visibility scope.
These two rules serve different actions (view/edit vs. transfer-ownership)
and should not be merged into one check.
"""
from .roles import ADMIN, SALES_MANAGER, INTL_SALES_MANAGER, SALES_REP

# entity_type -> the column that represents "owner" on that table.
# Column names aren't uniform across the schema (legacy naming: meetings
# uses organizer_id, leads uses assigned_to, customer_analyses uses
# analyst_id) — rather than rename 13 tables, this mapping absorbs the
# inconsistency in one place.
ENTITY_OWNER_COLUMN = {
    "customer": "owner_id",
    "opportunity": "owner_id",
    "quotation": "owner_id",
    "order": "owner_id",
    "shipment": "owner_id",
    "payment": "owner_id",
    "sample": "owner_id",
    "sales_log": "owner_id",
    "channel_partner": "owner_id",
    "exhibition": "owner_id",
    "meeting": "organizer_id",
    "lead": "assigned_to",
    "customer_analysis": "analyst_id",
}

# entity_type -> (table_name, owner_column). Used by the activity-log
# endpoint to look up "does the record behind this history entry still
# fall within what I'm allowed to see." Only covers modules that have
# actually had visibility scoping wired in — e.g. `registration` is
# deliberately excluded (stays fully visible to everyone, by design),
# and modules not yet migrated keep their pre-existing open behavior
# rather than being silently restricted.
ENTITY_TABLE_OWNER = {
    "customer": ("customers", "owner_id"),
    "opportunity": ("opportunities", "owner_id"),
    "quotation": ("quotations", "owner_id"),
    "order": ("orders", "owner_id"),
    "shipment": ("shipments", "owner_id"),
    "payment": ("payments", "owner_id"),
    "sample": ("samples", "owner_id"),
    "sales_log": ("sales_logs", "owner_id"),
    "channel_partner": ("channel_partners", "owner_id"),
}


def get_visible_user_ids(conn, user):
    """Self + every subordinate, recursively. Returns None for admin,
    meaning 'no filter — see everything'."""
    if user["role"] == ADMIN:
        return None
    rows = conn.execute(
        """WITH RECURSIVE subordinates(id) AS (
             SELECT id FROM users WHERE id = ?
             UNION ALL
             SELECT u.id FROM users u JOIN subordinates s ON u.manager_id = s.id
           )
           SELECT id FROM subordinates""",
        (user["id"],),
    ).fetchall()
    return [r["id"] for r in rows]


def can_manage_owner(conn, user, owner_id):
    """The owner themself, any ancestor of the owner (recursively), or
    admin — any of these can view/edit/transfer this record."""
    if user["role"] == ADMIN:
        return True
    if owner_id is None:
        return False
    visible = get_visible_user_ids(conn, user)
    return owner_id in visible


def can_initiate_transfer(user, current_owner_id):
    """Who can initiate an ownership transfer: the current owner
    (regardless of role), or anyone at sales_manager level or above
    (sales_manager / intl_sales_manager / admin). Note this differs
    from can_manage_owner — it does NOT require current_owner_id to
    fall within the initiator's own subordinate tree; manager-tier
    roles can initiate transfers outside their direct reports.
    """
    if user["role"] == ADMIN:
        return True
    if user["id"] == current_owner_id:
        return True
    return user["role"] in (SALES_MANAGER, INTL_SALES_MANAGER)


def is_eligible_transfer_recipient(conn, target_user_id):
    """A transfer recipient must be an active, sales-line role
    (sales_rep / sales_manager / intl_sales_manager). admin and
    registration cannot receive transferred ownership. This check does
    NOT consider the initiator's visibility scope — it's a property of
    the recipient, independent of who is doing the transferring.
    """
    if target_user_id is None:
        return False
    row = conn.execute(
        "SELECT role, status FROM users WHERE id = ?", (target_user_id,)
    ).fetchone()
    return bool(row) and row["status"] == "active" and row["role"] in (
        SALES_REP, SALES_MANAGER, INTL_SALES_MANAGER
    )


def would_create_cycle(conn, user_id, new_manager_id):
    """Would setting user_id's manager to new_manager_id create a cycle
    in the org tree?

    Used by the "set manager" admin UI: walk upward from new_manager_id;
    if the walk ever reaches user_id itself, assigning this manager
    would create a cycle, so the assignment is rejected.
    """
    current = new_manager_id
    seen = set()
    while current is not None:
        if current == user_id:
            return True
        if current in seen:
            # Defensive branch: a cycle already exists in the data
            # (shouldn't happen, since this check exists to prevent it),
            # but this avoids an infinite loop if it ever does.
            return True
        seen.add(current)
        row = conn.execute("SELECT manager_id FROM users WHERE id = ?", (current,)).fetchone()
        current = row["manager_id"] if row else None
    return False
