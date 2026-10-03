"""
JML Event Processor carrying out Joiner, Mover, and Leaver identity workflows.
"""

from datetime import datetime, timezone
import logging
import secrets
from typing import Any, Dict, List, Tuple

from jml.policy import MANAGED_ROLES, desired_roles

logger = logging.getLogger(__name__)


def process_event(
    event: Dict[str, Any],
    kc: Any,
    audit: Any,
    dry_run: bool = False,
    show_temp_passwords: bool = False,
) -> Tuple[str, str, str, str, str]:
    """
    Processes a single JML event record.
    Returns tuple: (event_id, action, username, status, summary_note)
    """
    event_id = str(event.get("event_id", "")).strip()
    action = str(event.get("event_type", "")).strip().upper()
    username = str(event.get("username", "")).strip()

    # 1. Validation
    if not event_id or not action or not username:
        missing_fields = []
        if not event_id:
            missing_fields.append("event_id")
        if not action:
            missing_fields.append("event_type")
        if not username:
            missing_fields.append("username")
        note = f"Field validation failure: missing required field(s): {', '.join(missing_fields)}"
        audit.log(
            event_id=event_id or "UNKNOWN",
            action=action or "UNKNOWN",
            username=username or "UNKNOWN",
            status="FAILED",
            details={"error": note},
        )
        return (event_id or "UNKNOWN", action or "UNKNOWN", username or "UNKNOWN", "FAILED", note)

    if action not in ("JOINER", "MOVER", "LEAVER"):
        note = f"Unsupported event_type '{action}'. Must be JOINER, MOVER, or LEAVER."
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="FAILED",
            details={"error": note},
        )
        return (event_id, action, username, "FAILED", note)

    # 2. Idempotency Check
    if audit.already_processed(event_id):
        note = f"Event '{event_id}' has already been processed."
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="SKIPPED",
            details={"reason": "Already processed"},
        )
        return (event_id, action, username, "SKIPPED", note)

    # Parse boolean manager flag
    is_manager_val = str(event.get("is_manager", "")).strip().lower()
    is_manager = is_manager_val in ("true", "1", "yes")

    department = str(event.get("department", "")).strip()

    try:
        if action == "JOINER":
            return _handle_joiner(
                event, kc, audit, event_id, action, username, department, is_manager, dry_run, show_temp_passwords
            )
        elif action == "MOVER":
            return _handle_mover(
                event, kc, audit, event_id, action, username, department, is_manager, dry_run
            )
        elif action == "LEAVER":
            return _handle_leaver(
                event, kc, audit, event_id, action, username, dry_run
            )

    except Exception as exc:
        note = f"Processing error: {str(exc)}"
        logger.error(f"Error processing event {event_id}: {exc}", exc_info=True)
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="FAILED",
            details={"error": str(exc)},
        )
        return (event_id, action, username, "FAILED", note)

    return (event_id, action, username, "FAILED", "Unhandled event execution flow")


def _handle_joiner(
    event: Dict[str, Any],
    kc: Any,
    audit: Any,
    event_id: str,
    action: str,
    username: str,
    department: str,
    is_manager: bool,
    dry_run: bool,
    show_temp_passwords: bool,
) -> Tuple[str, str, str, str, str]:
    first_name = str(event.get("first_name", "")).strip()
    last_name = str(event.get("last_name", "")).strip()
    email = str(event.get("email", "")).strip()
    employee_id = str(event.get("employee_id", "")).strip()

    if not first_name or not last_name or not email:
        note = "JOINER validation error: missing first_name, last_name, or email."
        audit.log(event_id, action, username, "FAILED", {"error": note})
        return (event_id, action, username, "FAILED", note)

    target_role_names = desired_roles(department, is_manager)

    if dry_run:
        note = f"[DRY RUN] Would create user '{username}' with roles: {sorted(list(target_role_names))}"
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="DRY_RUN",
            details={
                "employee_id": employee_id,
                "email": email,
                "department": department,
                "proposed_roles": sorted(list(target_role_names)),
            },
        )
        return (event_id, action, username, "DRY_RUN", note)

    # Check if user already exists
    existing = kc.find_user(username)
    if existing:
        note = f"User '{username}' already exists in Keycloak. Skipping creation."
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="SKIPPED",
            details={"reason": "User already exists in Keycloak"},
        )
        return (event_id, action, username, "SKIPPED", note)

    # Generate temporary password
    temp_pw = secrets.token_urlsafe(12)

    payload = {
        "username": username,
        "firstName": first_name,
        "lastName": last_name,
        "email": email,
        "enabled": True,
        "emailVerified": True,
        "requiredActions": ["UPDATE_PASSWORD"],
        "attributes": {
            "employee_id": [employee_id],
            "department": [department],
        },
    }

    user_id = kc.create_user(payload)
    kc.set_temp_password(user_id, temp_pw)

    # Assign roles
    role_objs = [kc.get_role(r) for r in target_role_names]
    kc.add_roles(user_id, role_objs)

    pw_msg = f" (Temp Password: {temp_pw})" if show_temp_passwords else ""
    note = f"User created cleanly. Roles assigned: {sorted(list(target_role_names))}{pw_msg}"

    audit.log(
        event_id=event_id,
        action=action,
        username=username,
        status="SUCCESS",
        details={
            "employee_id": employee_id,
            "email": email,
            "department": department,
            "roles_added": sorted(list(target_role_names)),
            "kc_user_id": user_id,
        },
    )
    audit.mark_processed(event_id)
    return (event_id, action, username, "SUCCESS", note)


def _handle_mover(
    event: Dict[str, Any],
    kc: Any,
    audit: Any,
    event_id: str,
    action: str,
    username: str,
    department: str,
    is_manager: bool,
    dry_run: bool,
) -> Tuple[str, str, str, str, str]:
    target_role_names = desired_roles(department, is_manager)

    if dry_run:
        note = f"[DRY RUN] Would update user '{username}' department to '{department}' and adjust roles."
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="DRY_RUN",
            details={
                "department": department,
                "proposed_roles": sorted(list(target_role_names)),
            },
        )
        return (event_id, action, username, "DRY_RUN", note)

    user = kc.find_user(username)
    if not user:
        note = f"MOVER error: User '{username}' does not exist in Keycloak."
        audit.log(event_id, action, username, "FAILED", {"error": note})
        return (event_id, action, username, "FAILED", note)

    user_id = user["id"]
    current_roles = kc.user_roles(user_id)
    current_managed = {r["name"] for r in current_roles if r["name"] in MANAGED_ROLES}

    to_add = target_role_names - current_managed
    to_remove = current_managed - target_role_names

    if to_remove:
        remove_objs = [kc.get_role(r) for r in to_remove]
        kc.remove_roles(user_id, remove_objs)

    if to_add:
        add_objs = [kc.get_role(r) for r in to_add]
        kc.add_roles(user_id, add_objs)

    kc.update_user(user_id, {"attributes": {"department": [department]}})

    note = f"Department updated to '{department}'. Added roles: {sorted(list(to_add))}, Removed roles: {sorted(list(to_remove))}"
    audit.log(
        event_id=event_id,
        action=action,
        username=username,
        status="SUCCESS",
        details={
            "new_department": department,
            "roles_before": sorted(list(current_managed)),
            "roles_after": sorted(list(target_role_names)),
            "roles_added": sorted(list(to_add)),
            "roles_removed": sorted(list(to_remove)),
        },
    )
    audit.mark_processed(event_id)
    return (event_id, action, username, "SUCCESS", note)


def _handle_leaver(
    event: Dict[str, Any],
    kc: Any,
    audit: Any,
    event_id: str,
    action: str,
    username: str,
    dry_run: bool,
) -> Tuple[str, str, str, str, str]:
    if dry_run:
        note = f"[DRY RUN] Would disable user '{username}', revoke sessions, and remove managed roles."
        audit.log(
            event_id=event_id,
            action=action,
            username=username,
            status="DRY_RUN",
            details={"disabled": True, "sessions_revoked": True},
        )
        return (event_id, action, username, "DRY_RUN", note)

    user = kc.find_user(username)
    if not user:
        note = f"LEAVER error: User '{username}' does not exist in Keycloak."
        audit.log(event_id, action, username, "FAILED", {"error": note})
        return (event_id, action, username, "FAILED", note)

    user_id = user["id"]
    leaver_time = datetime.now(timezone.utc).isoformat()

    kc.update_user(user_id, {"enabled": False, "attributes": {"leaver_date": [leaver_time]}})
    kc.logout_user(user_id)

    current_roles = kc.user_roles(user_id)
    current_managed = [r for r in current_roles if r["name"] in MANAGED_ROLES]
    if current_managed:
        kc.remove_roles(user_id, current_managed)

    removed_names = [r["name"] for r in current_managed]
    note = f"Account disabled, sessions logged out, removed roles: {sorted(removed_names)}"

    audit.log(
        event_id=event_id,
        action=action,
        username=username,
        status="SUCCESS",
        details={
            "disabled": True,
            "sessions_logged_out": True,
            "roles_removed": sorted(removed_names),
            "leaver_date": leaver_time,
        },
    )
    audit.mark_processed(event_id)
    return (event_id, action, username, "SUCCESS", note)
