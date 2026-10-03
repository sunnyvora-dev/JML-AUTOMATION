# Architecture & Technical Design - Identity Lifecycle Automation (JML)

## 1. System Architecture Overview

```
+-----------------------------------------------------------------------------------+
|                                 JML Automation CLI                                |
|                                                                                   |
|  +------------------+      +-------------------+      +------------------------+  |
|  |   CSV Feeder     | ---> |  Event Processor  | ---> |   Policy Engine        |  |
|  | (data/events.csv)|      | (jml/processor.py)|      |   (jml/policy.py)      |  |
|  +------------------+      +---------+---------+      +------------------------+  |
|                                      |                                            |
|                                      v                                            |
|                         +--------------------------+                              |
|                         |    Keycloak Admin Client |                              |
|                         | (jml/keycloak_client.py) |                              |
|                         +------------+-------------+                              |
|                                      |                                            |
|                                      v                                            |
|                         +--------------------------+                              |
|                         |    Audit Logger          |                              |
|                         |     (jml/audit.py)       |                              |
|                         +------------+-------------+                              |
+--------------------------------------|--------------------------------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
    +-----------------------------+         +-----------------------------+
    | Keycloak Server (v26.0)     |         | PostgreSQL Database (v16)   |
    | - Realm: company            |         | - Schema: jml               |
    | - REST Admin API            |         | - Tables: audit_log,        |
    | - Client: jml-automation    |         |           processed_events  |
    +-----------------------------+         +-----------------------------+
```

## 2. Component Descriptions

| Component | Module | Responsibility |
|---|---|---|
| **CLI Entrypoint** | `jml/__main__.py` | Parses arguments (`run`, `report`, `check`), sets up logging, formats tabular output. |
| **Config Loader** | `jml/config.py` | Reads environment variables from system `.env`, validates required options. |
| **Event Processor** | `jml/processor.py` | Validates records, handles idempotency, executes Joiner/Mover/Leaver workflows, captures error tracebacks. |
| **Policy Engine** | `jml/policy.py` | Maps departments to realm roles (`Engineering` -> `developer`, `HR` -> `hr`, etc.) and manages allowed role scope (`MANAGED_ROLES`). |
| **Keycloak Admin API** | `jml/keycloak_client.py` | Wrapper around Keycloak REST API, managing token acquisition, caching, user management, and exponential retries. |
| **Audit Logger** | `jml/audit.py` | Manages PostgreSQL database connections, idempotency key persistence (`processed_events`), and audit record storage (`audit_log`). |

## 3. JML Sequence Flows

### 3.1 Joiner Workflow
```
CSV Event -> Processor -> Audit.already_processed()? 
  |-- Yes -> Audit Log [SKIPPED] -> Done
  |-- No  -> Keycloak.find_user()
               |-- Found -> Audit Log [SKIPPED] -> Done
               |-- Not Found ->
                     1. Policy.desired_roles(dept, is_manager)
                     2. Keycloak.create_user(payload)
                     3. Keycloak.set_temp_password(user_id, temp_pw)
                     4. Keycloak.add_roles(user_id, desired_roles)
                     5. Audit.log(SUCCESS, details={roles_added, employee_id})
                     6. Audit.mark_processed(event_id)
```

### 3.2 Mover Workflow
```
CSV Event -> Processor -> Audit.already_processed()?
  |-- Yes -> Audit Log [SKIPPED] -> Done
  |-- No  -> Keycloak.find_user()
               |-- Not Found -> Audit Log [FAILED: User not found] -> Continue batch
               |-- Found ->
                     1. Policy.desired_roles(dept, is_manager)
                     2. Fetch user's current roles (intersect MANAGED_ROLES)
                     3. Compute roles_to_add = desired - current
                     4. Compute roles_to_remove = current - desired
                     5. Keycloak.remove_roles(user_id, roles_to_remove)
                     6. Keycloak.add_roles(user_id, roles_to_add)
                     7. Keycloak.update_user(dept attribute)
                     8. Audit.log(SUCCESS, details={before, after, added, removed})
                     9. Audit.mark_processed(event_id)
```

### 3.3 Leaver Workflow
```
CSV Event -> Processor -> Audit.already_processed()?
  |-- Yes -> Audit Log [SKIPPED] -> Done
  |-- No  -> Keycloak.find_user()
               |-- Not Found -> Audit Log [FAILED: User not found] -> Continue batch
               |-- Found ->
                     1. Keycloak.update_user(enabled=False, attributes={leaver_date})
                     2. Keycloak.logout_user(user_id) [Revoke active sessions]
                     3. Fetch current managed roles
                     4. Keycloak.remove_roles(user_id, current_managed_roles)
                     5. Audit.log(SUCCESS, details={roles_removed, disabled=True})
                     6. Audit.mark_processed(event_id)
```

## 4. Keycloak Admin REST API Endpoints Used

| Endpoint | HTTP Method | Description |
|---|---|---|
| `/realms/{realm}/protocol/openid-connect/token` | POST | Obtain access token using service account client credentials |
| `/admin/realms/{realm}/users` | GET | Search for existing user by exact username |
| `/admin/realms/{realm}/users` | POST | Create new user record |
| `/admin/realms/{realm}/users/{id}` | GET / PUT | Fetch or update user attributes and enabled status |
| `/admin/realms/{realm}/users/{id}/reset-password` | PUT | Set temporary initial password with required action |
| `/admin/realms/{realm}/users/{id}/logout` | POST | Invalidate all active user sessions across sessions store |
| `/admin/realms/{realm}/roles` | GET | Fetch role representations by name |
| `/admin/realms/{realm}/users/{id}/role-mappings/realm` | GET / POST / DELETE | View, assign, or revoke realm roles |

## 5. Data Model & Schema

### PostgreSQL Table: `audit_log`
```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_id TEXT NOT NULL,
    action TEXT NOT NULL, -- JOINER, MOVER, LEAVER
    target_username TEXT NOT NULL,
    status TEXT NOT NULL, -- SUCCESS, SKIPPED, FAILED, DRY_RUN
    actor TEXT NOT NULL DEFAULT 'jml-automation',
    details JSONB NOT NULL
);
CREATE INDEX idx_audit_log_target_username ON audit_log(target_username);
CREATE INDEX idx_audit_log_ts ON audit_log(ts);
```

### PostgreSQL Table: `processed_events`
```sql
CREATE TABLE processed_events (
    event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## 6. Security Decisions & Principles
1. **Least Privilege Service Account**: Dedicated client `jml-automation` assigned only `realm-management` roles: `manage-users`, `view-users`, `query-users`, `view-realm`. Full admin rights are avoided.
2. **Zero-Secret Logging**: Temporary passwords, access tokens, and client secrets are strictly stripped from all log messages, stdout, and JSONB audit details.
3. **Reversibility over Deletion**: Leaver workflow disables accounts (`enabled=False`) and strips active roles rather than performing hard SQL/Keycloak database deletes, preserving audit context.
4. **Managed Scope Isolation**: Automation only assigns/revokes roles defined in `MANAGED_ROLES`. Default system roles (e.g. `default-roles-company`, `offline_access`) are left untouched.

## 7. Error Handling & Retry Design
- **Transient Failures (5xx & Connection Errors)**: HTTP request wrapper uses exponential backoff (retries: 3, delay factor: 0.5s) via `urllib3` / `requests`.
- **Permanent Errors (4xx)**: Instantly raised as `KeycloakAPIError` without retrying.
- **Batch Resiliency**: Each event in a CSV batch is wrapped in a try/except block. Failed events create an audit log with status `FAILED` and traceback detail, allowing the remainder of the CSV batch to complete cleanly.

## 8. Future Cloud Architecture Path
To transition this automation to cloud-native AWS serverless infrastructure:
1. **Event Ingestion**: Replace CSV feeds with AWS SQS queues triggered by Workday / HR Webhooks.
2. **Execution**: Package `jml` core as an AWS Lambda function running in VPC.
3. **Secrets Management**: Retrieve Keycloak client secrets and Postgres credentials from AWS Secrets Manager.
4. **Database**: Store audit records in Amazon RDS PostgreSQL or Amazon DynamoDB with TTL.
