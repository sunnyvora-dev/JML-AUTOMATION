"""
Access Policy Engine mapping departments and managerial flags to Keycloak realm roles.
"""

from typing import Set

DEPT_ROLE = {
    "engineering": "developer",
    "hr": "hr",
    "finance": "finance",
    "sales": "sales",
}

MANAGED_ROLES: Set[str] = {
    "employee",
    "developer",
    "hr",
    "finance",
    "sales",
    "manager",
}


def desired_roles(department: str, is_manager: bool) -> Set[str]:
    """
    Computes the set of target managed roles for a user based on department and manager flag.
    Always includes the baseline 'employee' role.
    """
    roles: Set[str] = {"employee"}
    dept_key = (department or "").strip().lower()

    if dept_key in DEPT_ROLE:
        roles.add(DEPT_ROLE[dept_key])

    if is_manager:
        roles.add("manager")

    return roles
