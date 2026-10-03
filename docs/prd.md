# Product Requirement Document (PRD) - Identity Lifecycle Automation (JML)

## 1. Overview
Identity Lifecycle Automation (JML) is a Python-based enterprise IAM automation solution designed to process HR identity lifecycle events—**Joiner**, **Mover**, and **Leaver**—and synchronize user access state with Keycloak identity provider via its Admin REST API, recording all operations in a PostgreSQL audit log.

## 2. Problem Statement
Manual onboarding, internal role transfers, and offboarding lead to:
- **Security vulnerabilities**: Delayed offboarding leaves active credentials accessible to terminated employees.
- **Access sprawl / Over-privileging**: Employees accumulate roles when moving departments without old access revoked.
- **Operational delays**: IT helpdesks spend manual effort provisioning standard accounts and assigning roles.
- **Audit compliance gaps**: Lack of central, tamper-evident audit logging for user access state changes.

## 3. Goals & Non-Goals
### Goals
- Automate user provisioning, role assignments, role transitions, and account deactivations using Keycloak Admin REST APIs.
- Enforce Role-Based Access Control (RBAC) policies mapped strictly by department and managerial status.
- Provide idempotent event processing to prevent duplicate account creation or state corruption.
- Record structured JSONB audit trails in PostgreSQL for every operation (including dry-run and failures).
- Provide a robust CLI interface for operations, reporting, and health checks.

### Non-Goals
- Real-time event streaming / Webhook listeners (CSV file batch input is scope for MVP).
- Full Identity Governance and Administration (IGA) recertification campaigns.
- Direct database mutation of Keycloak internals (all interactions use Keycloak REST API).

## 4. Target Personas
| Persona | Role | Needs |
|---|---|---|
| **HR Administrator** | Generates HR event feeds (Joiner, Mover, Leaver) | Reliable execution of identity changes without manual IT tickets |
| **IT Security / IAM Admin** | Operates & monitors JML system | Least privilege service accounts, clear CLI reporting, dry-run safety |
| **Compliance Auditor** | Reviews security and access logs | Complete, timestamped audit log of all access modifications and failures |

## 5. Functional Requirements
- **FR1: Joiner Process**
  - Provision new user in Keycloak with `enabled=True`, `emailVerified=True`, standard name fields, and attributes (`employee_id`, `department`).
  - Assign department-specific managed roles and optional `manager` role.
  - Set initial temporary password with required action `UPDATE_PASSWORD`.
- **FR2: Mover Process**
  - Verify user existence.
  - Update user `department` attribute.
  - Compute current managed roles vs desired managed roles. Reconcile by adding required new roles and revoking old obsolete roles. Leave unmanaged/default Keycloak roles untouched.
- **FR3: Leaver Process**
  - Verify user existence.
  - Set `enabled=False` to deactivate account immediately.
  - Revoke all managed roles.
  - Terminate all active Keycloak user sessions (`logout`).
  - Set `leaver_date` user attribute. Retain user record for audit compliance (never hard delete).
- **FR4: Dry-Run Mode**
  - Simulate Joiner, Mover, and Leaver actions without executing Keycloak API state mutations.
  - Log audit records with status `DRY_RUN`.
- **FR5: Idempotency & Fault Tolerance**
  - Track processed `event_id` in database. Skip duplicate events with status `SKIPPED`.
  - Process batch events iteratively; handle single-event failures gracefully without halting remaining events.
- **FR6: Audit Trail & CLI Reporting**
  - Persist event details, timing, status (`SUCCESS`, `SKIPPED`, `FAILED`, `DRY_RUN`), and role diffs in PostgreSQL.
  - Provide CLI commands (`run`, `report`, `check`) with colored output.

## 6. Non-Functional Requirements
- **Security**: Service account uses least-privilege realm roles (`manage-users`, `view-users`, `query-users`, `view-realm`). Secrets, passwords, and OAuth tokens are never logged or stored in audit records.
- **Performance**: Execute batch of 100 events in under 30 seconds.
- **Reliability**: Exponential backoff retry mechanism (max 3 retries) for transient Keycloak 5xx errors and network failures.

## 7. Success Metrics
- 100% automated user provisioning without manual intervention.
- Zero credential/secret leakage in logs or database tables.
- 100% audit log coverage for all processed HR events.

## 8. Acceptance Criteria
- `python -m jml check` succeeds when Keycloak and Postgres containers are healthy.
- `python -m jml run --file data/events.csv` processes Joiner, Mover, Leaver, duplicates, and invalid events correctly.
- `python -m jml report` displays complete, queryable history of user state transitions.
- All unit tests in `pytest` pass with 100% mock coverage.

## 9. Risk Assessment
| Risk | Severity | Mitigation |
|---|---|---|
| Keycloak Service Account secret compromised | High | Rotate client secret; enforce network boundary / container network security |
| Unmanaged attribute loss in Keycloak 24+ | Medium | Explicitly configure realm user-profile or enable unmanaged attributes |
| Mass account deactivation by malformed CSV feed | High | Mandatory `--dry-run` flag support and approval flow capability for large batches |
