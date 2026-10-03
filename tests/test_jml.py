"""
Comprehensive Pytest Test Suite for JML Automation using FakeKeycloak & FakeAudit.
"""

from typing import Any, Dict, List, Optional, Set
import pytest
import requests
from unittest.mock import MagicMock, patch

from jml.policy import DEPT_ROLE, MANAGED_ROLES, desired_roles
from jml.processor import process_event
from jml.keycloak_client import KeycloakAdmin, KeycloakAPIError


class FakeKeycloak:
    def __init__(self):
        self.users: Dict[str, Dict[str, Any]] = {}
        self.roles: Dict[str, Dict[str, Any]] = {
            "employee": {"id": "role-emp-id", "name": "employee"},
            "developer": {"id": "role-dev-id", "name": "developer"},
            "hr": {"id": "role-hr-id", "name": "hr"},
            "finance": {"id": "role-fin-id", "name": "finance"},
            "sales": {"id": "role-sales-id", "name": "sales"},
            "manager": {"id": "role-mgr-id", "name": "manager"},
            "default-roles-company": {"id": "role-sys-id", "name": "default-roles-company"},
        }
        self.user_role_mappings: Dict[str, Set[str]] = {}
        self.active_sessions: Dict[str, List[str]] = {}
        self.passwords: Dict[str, str] = {}
        self._user_counter = 1

    def find_user(self, username: str) -> Optional[Dict[str, Any]]:
        for u in self.users.values():
            if u.get("username", "").lower() == username.lower():
                return u.copy()
        return None

    def create_user(self, payload: Dict[str, Any]) -> str:
        user_id = f"usr-uuid-{self._user_counter}"
        self._user_counter += 1
        user_copy = payload.copy()
        user_copy["id"] = user_id
        self.users[user_id] = user_copy
        self.user_role_mappings[user_id] = {"default-roles-company"}  # Unmanaged system role
        self.active_sessions[user_id] = ["session-1", "session-2"]
        return user_id

    def set_temp_password(self, user_id: str, password: str) -> None:
        self.passwords[user_id] = password

    def get_role(self, role_name: str) -> Dict[str, Any]:
        if role_name in self.roles:
            return self.roles[role_name]
        return {"id": f"role-{role_name}-id", "name": role_name}

    def user_roles(self, user_id: str) -> List[Dict[str, Any]]:
        mapped_names = self.user_role_mappings.get(user_id, set())
        return [self.get_role(name) for name in mapped_names]

    def add_roles(self, user_id: str, roles: List[Dict[str, Any]]) -> None:
        if user_id not in self.user_role_mappings:
            self.user_role_mappings[user_id] = set()
        for r in roles:
            self.user_role_mappings[user_id].add(r["name"])

    def remove_roles(self, user_id: str, roles: List[Dict[str, Any]]) -> None:
        if user_id in self.user_role_mappings:
            for r in roles:
                self.user_role_mappings[user_id].discard(r["name"])

    def update_user(self, user_id: str, payload: Dict[str, Any]) -> None:
        if user_id in self.users:
            u = self.users[user_id]
            for k, v in payload.items():
                if k == "attributes" and isinstance(v, dict):
                    attrs = u.get("attributes", {}).copy()
                    attrs.update(v)
                    u["attributes"] = attrs
                else:
                    u[k] = v

    def logout_user(self, user_id: str) -> None:
        if user_id in self.active_sessions:
            self.active_sessions[user_id] = []


class FakeAudit:
    def __init__(self):
        self.logs: List[Dict[str, Any]] = []
        self.processed: Set[str] = set()

    def log(self, event_id: str, action: str, username: str, status: str, details: Dict[str, Any], actor: str = "jml-automation") -> None:
        from jml.audit import Audit
        clean_details = Audit._sanitize_details(details)
        self.logs.append({
            "event_id": event_id,
            "action": action,
            "username": username,
            "status": status,
            "details": clean_details,
            "actor": actor,
        })

    def already_processed(self, event_id: str) -> bool:
        return event_id in self.processed

    def mark_processed(self, event_id: str) -> None:
        self.processed.add(event_id)

    def report(self, username: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        filtered = [l for l in self.logs if not username or l["username"] == username]
        return filtered[:limit]


# --- Policy Unit Tests ---
def test_policy_department_mapping():
    assert desired_roles("Engineering", False) == {"employee", "developer"}
    assert desired_roles("HR", False) == {"employee", "hr"}
    assert desired_roles("Finance", False) == {"employee", "finance"}
    assert desired_roles("Sales", False) == {"employee", "sales"}
    assert desired_roles("UnknownDept", False) == {"employee"}


def test_policy_manager_flag():
    roles = desired_roles("Engineering", is_manager=True)
    assert roles == {"employee", "developer", "manager"}


# --- Processor Workflow Tests ---
def test_joiner_creates_user_with_roles_and_attributes():
    kc = FakeKeycloak()
    audit = FakeAudit()
    event = {
        "event_id": "EVT-01",
        "event_type": "JOINER",
        "employee_id": "EMP-100",
        "username": "charlie.eng",
        "first_name": "Charlie",
        "last_name": "Engineer",
        "email": "charlie@company.com",
        "department": "Engineering",
        "is_manager": "false",
    }

    res = process_event(event, kc, audit)
    assert res[3] == "SUCCESS"
    assert audit.already_processed("EVT-01")

    u = kc.find_user("charlie.eng")
    assert u is not None
    assert u["enabled"] is True
    assert u["attributes"]["department"] == ["Engineering"]
    assert u["attributes"]["employee_id"] == ["EMP-100"]

    roles = {r["name"] for r in kc.user_roles(u["id"])}
    assert roles == {"employee", "developer", "default-roles-company"}


def test_joiner_repeat_idempotency():
    kc = FakeKeycloak()
    audit = FakeAudit()
    event = {
        "event_id": "EVT-01",
        "event_type": "JOINER",
        "employee_id": "EMP-100",
        "username": "charlie.eng",
        "first_name": "Charlie",
        "last_name": "Engineer",
        "email": "charlie@company.com",
        "department": "Engineering",
        "is_manager": "false",
    }

    process_event(event, kc, audit)
    res2 = process_event(event, kc, audit)
    assert res2[3] == "SKIPPED"
    assert len([l for l in audit.logs if l["status"] == "SKIPPED"]) == 1


def test_mover_updates_roles_and_department():
    kc = FakeKeycloak()
    audit = FakeAudit()

    # Create initial user in Engineering
    join_ev = {
        "event_id": "EVT-01",
        "event_type": "JOINER",
        "employee_id": "EMP-100",
        "username": "david.mover",
        "first_name": "David",
        "last_name": "Mover",
        "email": "david@company.com",
        "department": "Engineering",
        "is_manager": "false",
    }
    process_event(join_ev, kc, audit)

    # Move to Sales as Manager
    move_ev = {
        "event_id": "EVT-02",
        "event_type": "MOVER",
        "employee_id": "EMP-100",
        "username": "david.mover",
        "department": "Sales",
        "is_manager": "true",
    }
    res = process_event(move_ev, kc, audit)
    assert res[3] == "SUCCESS"

    u = kc.find_user("david.mover")
    assert u["attributes"]["department"] == ["Sales"]

    roles = {r["name"] for r in kc.user_roles(u["id"])}
    assert roles == {"employee", "sales", "manager", "default-roles-company"}
    assert "developer" not in roles  # Old role stripped


def test_leaver_disables_account_and_logs_out_sessions():
    kc = FakeKeycloak()
    audit = FakeAudit()

    join_ev = {
        "event_id": "EVT-01",
        "event_type": "JOINER",
        "employee_id": "EMP-100",
        "username": "eve.leaver",
        "first_name": "Eve",
        "last_name": "Leaver",
        "email": "eve@company.com",
        "department": "Finance",
        "is_manager": "false",
    }
    process_event(join_ev, kc, audit)

    leave_ev = {
        "event_id": "EVT-03",
        "event_type": "LEAVER",
        "username": "eve.leaver",
    }
    res = process_event(leave_ev, kc, audit)
    assert res[3] == "SUCCESS"

    u = kc.find_user("eve.leaver")
    assert u["enabled"] is False
    assert "leaver_date" in u["attributes"]

    roles = {r["name"] for r in kc.user_roles(u["id"])}
    assert roles == {"default-roles-company"}  # Managed roles stripped, unmanaged system role retained
    assert kc.active_sessions[u["id"]] == []


def test_unknown_user_mover_or_leaver_fails_gracefully():
    kc = FakeKeycloak()
    audit = FakeAudit()

    move_ev = {
        "event_id": "EVT-99",
        "event_type": "MOVER",
        "username": "unknown.user",
        "department": "Sales",
    }
    res = process_event(move_ev, kc, audit)
    assert res[3] == "FAILED"
    assert audit.logs[-1]["status"] == "FAILED"


def test_validation_failure_missing_fields_or_bad_type():
    kc = FakeKeycloak()
    audit = FakeAudit()

    bad_ev1 = {"event_id": "EVT-00", "event_type": "JOINER"}
    res1 = process_event(bad_ev1, kc, audit)
    assert res1[3] == "FAILED"

    bad_ev2 = {"event_id": "EVT-00", "event_type": "PROMOTE", "username": "alice"}
    res2 = process_event(bad_ev2, kc, audit)
    assert res2[3] == "FAILED"


def test_dry_run_mode_makes_no_changes():
    kc = FakeKeycloak()
    audit = FakeAudit()

    join_ev = {
        "event_id": "EVT-DRY",
        "event_type": "JOINER",
        "employee_id": "EMP-DRY",
        "username": "dry.user",
        "first_name": "Dry",
        "last_name": "Run",
        "email": "dry@company.com",
        "department": "Engineering",
    }
    res = process_event(join_ev, kc, audit, dry_run=True)
    assert res[3] == "DRY_RUN"
    assert kc.find_user("dry.user") is None
    assert not audit.already_processed("EVT-DRY")


def test_secrets_sanitized_from_audit():
    audit = FakeAudit()
    audit.log(
        event_id="EVT-SEC",
        action="TEST",
        username="sec.user",
        status="SUCCESS",
        details={"user_password": "supersecretpassword", "nested": {"token": "bearer-abc"}},
    )
    details = audit.logs[0]["details"]
    assert details["user_password"] == "[REDACTED]"
    assert details["nested"]["token"] == "[REDACTED]"


def test_keycloak_retry_logic_5xx_and_4xx():
    mock_session = MagicMock()

    # 1. Test 500 error retried max_retries times
    resp_500 = MagicMock()
    resp_500.status_code = 500
    mock_session.request.return_value = resp_500

    admin = KeycloakAdmin(
        base_url="http://localhost:8080",
        realm="company",
        client_id="jml-automation",
        client_secret="secret",
        session=mock_session,
        max_retries=2,
        backoff_factor=0.01,
    )

    with pytest.raises(KeycloakAPIError) as exc_info:
        admin._request("GET", "/test-500", authenticated=False)
    assert exc_info.value.status_code == 500
    assert mock_session.request.call_count == 3  # Initial + 2 retries

    # 2. Test 401 client error NOT retried
    mock_session.reset_mock()
    resp_401 = MagicMock()
    resp_401.status_code = 401
    resp_401.json.return_value = {"error_description": "Invalid credentials"}
    mock_session.request.return_value = resp_401

    with pytest.raises(KeycloakAPIError) as exc_info401:
        admin._request("GET", "/test-401", authenticated=False)
    assert exc_info401.value.status_code == 401
    assert mock_session.request.call_count == 1  # No retries for 4xx


def test_csv_parsing(tmp_path):
    csv_file = tmp_path / "events.csv"
    csv_file.write_text(
        "event_id,event_type,employee_id,username,first_name,last_name,email,department,is_manager\n"
        "EVT-01,JOINER,EMP-1,test.user,Test,User,test@company.com,Engineering,false\n"
    )

    import csv
    events = []
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            events.append(r)

    assert len(events) == 1
    assert events[0]["event_id"] == "EVT-01"
    assert events[0]["username"] == "test.user"
    assert events[0]["department"] == "Engineering"

