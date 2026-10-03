# Project Memory & Knowledge Base - Identity Lifecycle Automation (JML)

## 1. Project Snapshot
- **Project Name**: Identity Lifecycle Automation (Joiner-Mover-Leaver)
- **Primary Objective**: Automated IAM provisioning, role reconciliation, and account deactivation in Keycloak using REST APIs with PostgreSQL audit logging.
- **Current Status**: Complete. All core modules, infrastructure manifests, test suites (12/12 passing), and documentation are ready.

## 2. Key Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Identity Service** | Keycloak 26.0 (Admin REST API) | Industry standard open-source IdP with robust REST API and realm management capability |
| **Audit Storage** | PostgreSQL 16 (`JSONB` column) | Relational engine with fast indexing for usernames/timestamps and flexible JSON schema for event details |
| **API Client Session** | `requests.Session` with token caching | Eliminates per-request auth overhead; auto-renews tokens when within 30s of expiry |
| **Role Reconciliation** | Differential math (`want - have`, `have - want`) | Guarantees atomic additions/removals while strictly leaving system roles (`default-roles-company`) untouched |
| **Offboarding Strategy** | Disable account (`enabled=False`) + logout sessions | Preserves compliance audit history, prevents hard deletes, and ensures instant session revocation |

## 3. Critical Gotchas & Workarounds
1. **Keycloak 24+ User Attributes Validation**:
   - *Problem*: Keycloak 24+ drops custom attributes (`employee_id`, `department`) unless enabled in Realm User Profile or Unmanaged Attributes settings.
   - *Solution*: Enabled `"unmanagedAttributePolicy": "ENABLED"` in `keycloak/realm-company.json`.
2. **Missing User Name / Email Required Actions**:
   - *Problem*: Keycloak enforces mandatory `email`, `firstName`, and `lastName`. Missing fields cause silent login blocks or API errors.
   - *Solution*: Enforce strictly via CSV field validation in `jml/processor.py`.
3. **Keycloak Admin Role Scope**:
   - *Problem*: Giving service account `admin` role violates least-privilege principles.
   - *Solution*: Assign strictly `realm-management` roles: `manage-users`, `view-users`, `query-users`, `view-realm`.

## 4. Useful Operations & Commands

```bash
# Build and run containers
docker compose up -d

# Check service status
python -m jml check

# Execute dry-run JML batch
python -m jml run --file data/events.csv --dry-run

# Execute live JML batch
python -m jml run --file data/events.csv --show-temp-passwords

# Query audit log
python -m jml report --limit 50

# Run full pytest suite with coverage
python -m pytest tests/ -v
```

## 5. Interview Talking Points (Resume Highlights)
- **Role Reconciliation Algorithm**: "Designed a set-based differential algorithm (`desired - current` and `current - desired`) to atomically reconcile Keycloak realm roles without disrupting non-managed system roles."
- **Least Privilege Service Account**: "Configured Keycloak client credentials flow with custom `realm-management` client roles (`manage-users`, `view-users`), avoiding master realm superuser access."
- **Idempotency & Resiliency**: "Implemented duplicate event suppression using PostgreSQL primary key locks (`processed_events`) and built exponential backoff retries for transient 5xx HTTP errors."
- **Zero-Trust Audit Log**: "Architected a PostgreSQL JSONB audit subsystem that records exact before/after role state transitions while enforcing secret masking on stdout and DB storage."

## 6. Verification & Validation Summary
- `python -m pytest tests/ -v`: 12 test cases executed, 100% pass rate.
- Realm JSON validated against Keycloak 26 import schema.
- CSV dataset tested against validation & idempotency handlers.
