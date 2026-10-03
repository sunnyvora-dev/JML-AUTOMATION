# Design Specifications - Identity Lifecycle Automation (JML)

## 1. CSV Event Feed Format
The feed file is a standard UTF-8 CSV located at `data/events.csv` with the following header and schema:

```csv
event_id,event_type,employee_id,username,first_name,last_name,email,department,is_manager
EVT-1001,JOINER,EMP-001,alice.eng,Alice,Engineer,alice.eng@company.com,Engineering,false
EVT-1002,JOINER,EMP-002,bob.fin,Bob,Finance,bob.fin@company.com,Finance,false
EVT-1003,MOVER,EMP-001,alice.eng,Alice,Engineer,alice.eng@company.com,Sales,true
EVT-1004,LEAVER,EMP-002,bob.fin,Bob,Finance,bob.fin@company.com,Finance,false
EVT-1005,JOINER,EMP-001,alice.eng,Alice,Engineer,alice.eng@company.com,Engineering,false
EVT-1006,MOVER,EMP-999,ghost.user,Ghost,User,ghost@company.com,Engineering,false
EVT-1007,JOINER,EMP-003,,Missing,LastName,missing@company.com,Sales,false
```

### Data Validation Matrix
- `event_id`: Non-empty string.
- `event_type`: Must be one of `JOINER`, `MOVER`, `LEAVER`.
- `employee_id`: Unique HR identifier string.
- `username`: Keycloak unique account handle. Required for all events.
- `first_name`, `last_name`, `email`: Required for `JOINER` events.
- `department`: Must map to known policy department (`Engineering`, `HR`, `Finance`, `Sales`).
- `is_manager`: Boolean string (`true`, `false`, `1`, `0`).

## 2. Access Policy Engine (`jml/policy.py`)

### Managed Realm Roles Scope
```python
MANAGED_ROLES = {"employee", "developer", "hr", "finance", "sales", "manager"}
```

### Department to Role Mapping
| Department | Core Role Assigned |
|---|---|
| `Engineering` | `developer` |
| `HR` | `hr` |
| `Finance` | `finance` |
| `Sales` | `sales` |

### Role Resolution Logic
Every active user automatically receives the baseline `employee` role.
If `is_manager` is true, the `manager` role is appended.

```python
def desired_roles(department: str, is_manager: bool) -> set[str]:
    roles = {"employee"}
    dept_lower = department.strip().lower()
    if dept_lower == "engineering":
        roles.add("developer")
    elif dept_lower == "hr":
        roles.add("hr")
    elif dept_lower == "finance":
        roles.add("finance")
    elif dept_lower == "sales":
        roles.add("sales")
    
    if is_manager:
        roles.add("manager")
    return roles
```

## 3. Keycloak Realm Configuration (`keycloak/realm-company.json`)

- **Realm Name**: `company`
- **Realm Roles**: `employee`, `developer`, `manager`, `hr`, `finance`, `sales`
- **Confidential Client**: `jml-automation`
  - `publicClient`: `false`
  - `serviceAccountsEnabled`: `true`
  - `standardFlowEnabled`: `false`
  - `directAccessGrantsEnabled`: `false`
  - `secret`: `jml-automation-secret-demo-123`
- **Service Account Permissions**: Assigned client roles under `realm-management`:
  - `manage-users`
  - `view-users`
  - `query-users`
  - `view-realm`
- **Integrations**: Includes `company-app` public client (`standardFlowEnabled: true`, PKCE `S256`, redirect `http://localhost:5000/*`) for compatibility with existing RBAC standard flow authentication projects.
- **User Attributes Compatibility**: Configured user-profile attributes for `employee_id` and `department` to adhere to Keycloak 24+ strict unmanaged attributes validation rules.

## 4. PostgreSQL Database Schema (`sql/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_username TEXT NOT NULL,
    status TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'jml-automation',
    details JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_target_username ON audit_log(target_username);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## 5. Audit Record Details Format (JSONB)

### Joiner Audit Detail Example
```json
{
  "employee_id": "EMP-001",
  "email": "alice.eng@company.com",
  "department": "Engineering",
  "roles_added": ["employee", "developer"],
  "kc_user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Mover Audit Detail Example
```json
{
  "previous_department": "Engineering",
  "new_department": "Sales",
  "roles_before": ["employee", "developer"],
  "roles_after": ["employee", "sales", "manager"],
  "roles_added": ["sales", "manager"],
  "roles_removed": ["developer"]
}
```

### Leaver Audit Detail Example
```json
{
  "disabled": true,
  "sessions_logged_out": true,
  "roles_removed": ["employee", "sales", "manager"],
  "leaver_date": "2026-10-03T16:00:00Z"
}
```

## 6. CLI Command Line Design

```bash
# Health check command
python -m jml check

# Execution command (Dry-run mode)
python -m jml run --file data/events.csv --dry-run

# Execution command (Live execution)
python -m jml run --file data/events.csv [--show-temp-passwords]

# Audit report command
python -m jml report [--user alice.eng] [--limit 20]
```

### CLI Execution Summary Table Output (Sample)
```
+----------+---------+------------+---------+----------------------------------------------+
| Event ID | Action  | Username   | Status  | Details / Summary                            |
+----------+---------+------------+---------+----------------------------------------------+
| EVT-1001 | JOINER  | alice.eng  | SUCCESS | User created; roles: [developer, employee]   |
| EVT-1002 | JOINER  | bob.fin    | SUCCESS | User created; roles: [employee, finance]     |
| EVT-1003 | MOVER   | alice.eng  | SUCCESS | Roles added: [manager, sales], rem: [dev]    |
| EVT-1004 | LEAVER  | bob.fin    | SUCCESS | User disabled; sessions revoked              |
| EVT-1005 | JOINER  | alice.eng  | SKIPPED | Event EVT-1005 already processed             |
| EVT-1006 | MOVER   | ghost.user | FAILED  | User 'ghost.user' does not exist             |
| EVT-1007 | JOINER  | missing_usr| FAILED  | Field validation error: 'username' missing   |
+----------+---------+------------+---------+----------------------------------------------+
Total Events Processed: 7 | Success: 4 | Skipped: 1 | Failed: 2
```

## 7. Automated Demo Workflow Script (`scripts/demo.sh`)
1. Run `python -m jml check` to confirm service connectivity.
2. Run `python -m jml run --file data/events.csv --dry-run` to preview state modifications.
3. Run `python -m jml run --file data/events.csv` to apply real modifications to Keycloak and Postgres.
4. Run `python -m jml report` to display audit log history.
5. Re-run `python -m jml run --file data/events.csv` to demonstrate idempotency skipping.
