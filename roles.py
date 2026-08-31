"""
Single source of truth for the sales-line role hierarchy.

Design note (from the original refactor):
Role strings ('admin' / 'manager' / 'sales' / ...) used to be scattered
across auth.py / users.py / customers.py, and duplicated again in the
frontend. This module centralizes them so every layer of the app imports
from one place, and so the visibility-scoping logic (see visibility.py)
has a single, authoritative hierarchy to walk.
"""

ADMIN = "admin"
INTL_SALES_MANAGER = "intl_sales_manager"
SALES_MANAGER = "sales_manager"
SALES_REP = "sales_rep"
REGISTRATION = "registration"  # independent compliance track, not part of the sales line

ALL_ROLES = [ADMIN, INTL_SALES_MANAGER, SALES_MANAGER, SALES_REP, REGISTRATION]

ROLE_LABELS = {
    ADMIN: "Administrator",
    INTL_SALES_MANAGER: "International Sales Manager",
    SALES_MANAGER: "Sales Manager",
    SALES_REP: "Sales Representative",
    REGISTRATION: "Registration Specialist",
}

# Sales-line hierarchy, highest to lowest. `registration` is a separate
# functional permission and is deliberately NOT part of this chain.
SALES_HIERARCHY = [ADMIN, INTL_SALES_MANAGER, SALES_MANAGER, SALES_REP]

# When assigning a user's manager, this enforces "one level up only" —
# no skipping tiers. admin/registration are absent on purpose: they sit
# outside the hierarchy and cannot have a manager assigned.
ALLOWED_MANAGER_ROLE = {
    SALES_REP: SALES_MANAGER,
    SALES_MANAGER: INTL_SALES_MANAGER,
    INTL_SALES_MANAGER: ADMIN,
}
