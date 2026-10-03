# Identity Lifecycle Automation (Joiner-Mover-Leaver)

> **Portfolio-Grade IAM Automation Engine for Enterprise User Provisioning, Role Reconciliation, and Audit Compliance.**

![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![Keycloak](https://img.shields.io/badge/Keycloak-26.0-blue?logo=keycloak)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue?logo=postgresql)
![Docker](https://img.shields.io/badge/Docker_Compose-Enabled-blue?logo=docker)
![Tests](https://img.shields.io/badge/Pytest-100%25_Passing-brightgreen?logo=pytest)

---

## 📌 Executive Summary
**Identity Lifecycle Automation (JML)** is a Python-based enterprise IAM workflow engine that automates HR identity lifecycle events (**Joiner**, **Mover**, and **Leaver**). Operating against Keycloak's Admin REST API, it automates user account provisioning, role reconciliation, and account deactivation while capturing immutable JSONB operational records in PostgreSQL for security auditing.

### Resume Highlights Supported:
1. **Python-based automation workflow** for Joiner, Mover, and Leaver (JML) identity processes.
2. **Automated user provisioning, role assignment, role changes, and account deactivation** via Keycloak REST APIs.
3. **Basic audit logging** to track user and access changes and troubleshoot provisioning issues.

---

## 🏗 System Architecture & Workflow Diagram

```
 +------------------+      +-------------------+      +------------------------+
 |   CSV HR Feed    | ---> |  Event Processor  | ---> |   Policy Engine        |
 | (data/events.csv)|      | (jml/processor.py)|      |   (jml/policy.py)      |
 +------------------+      +---------+---------+      +------------------------+
                                     |
                                     v
                        +--------------------------+
                        | Keycloak Admin REST API  |
                        | (jml/keycloak_client.py) |
                        +------------+-------------+
                                     |
                                     v
                        +--------------------------+
                        | PostgreSQL Audit Logger  |
                        |     (jml/audit.py)       |
                        +--------------------------+
```

---

## ⚡ JML Event Execution Matrix

| HR Event Type | Target Keycloak Operations | Role Differential Handling | Audit Trail Status |
|---|---|---|---|
| **JOINER** | Create user (`enabled=true`, `emailVerified=true`), set attributes (`employee_id`, `department`), set temp password, set `UPDATE_PASSWORD` action. | Assign baseline `employee` role + department role (e.g. `developer`) + `manager` (if flagged). | `SUCCESS` / `SKIPPED` |
| **MOVER** | Verify user existence, update `department` user attribute. | Compute `want - have` (assign new department/manager roles) and `have - want` (strip old department roles). System roles left untouched. | `SUCCESS` / `FAILED` |
| **LEAVER** | Disable account (`enabled=false`), revoke all active sessions (`logout`), stamp `leaver_date` attribute. Account retained for audit compliance. | Revoke all `MANAGED_ROLES` (`employee`, `developer`, `sales`, etc.). System roles left untouched. | `SUCCESS` / `FAILED` |

---

## 🚀 Quick Start Guide

### 1. Prerequisites & Environment Setup
Ensure Python 3.12+ and Docker Desktop are installed on your workstation.

```bash
# Clone the repository and enter directory
cd jml-automation

# Copy sample environment configuration
cp .env.example .env

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install required dependencies
pip install requests psycopg2-binary pytest
```

### 2. Launch Local Infrastructure
Boot up local Keycloak 26 and PostgreSQL 16 containers via Docker Compose:

```bash
docker compose up -d
```
*Keycloak will start dev mode at `http://localhost:8080` (admin/admin123) and import `keycloak/realm-company.json` automatically.*

### 3. Verify Health & Service Connections
```bash
python -m jml check
```

### 4. Run Dry-Run Simulation (Safe Mode)
```bash
python -m jml run --file data/events.csv --dry-run
```

### 5. Execute Live Batch Processing
```bash
python -m jml run --file data/events.csv --show-temp-passwords
```

### 6. Query Operational Audit Logs
```bash
python -m jml report --limit 20
```

---

## 📄 CSV Feed Format (`data/events.csv`)

```csv
event_id,event_type,employee_id,username,first_name,last_name,email,department,is_manager
EVT-1001,JOINER,EMP-001,alice.eng,Alice,Engineer,alice.eng@company.com,Engineering,false
EVT-1002,JOINER,EMP-002,bob.fin,Bob,Finance,bob.fin@company.com,Finance,false
EVT-1003,MOVER,EMP-001,alice.eng,Alice,Engineer,alice.eng@company.com,Sales,true
EVT-1004,LEAVER,EMP-002,bob.fin,Bob,Finance,bob.fin@company.com,Finance,false
EVT-1001,JOINER,EMP-001,alice.eng,Alice,Engineer,alice.eng@company.com,Engineering,false
EVT-1006,MOVER,EMP-999,ghost.user,Ghost,User,ghost@company.com,Engineering,false
EVT-1007,JOINER,EMP-003,,Missing,LastName,missing@company.com,Sales,false
```

---

## 📊 Sample Audit Report Output

```
=== JML Audit Log Report (Showing top 5 records) ===
-----------------------------------------------------------------------------------------------------------------------
ID     | TIMESTAMP                | EVENT ID   | ACTION   | TARGET         | STATUS     | DETAILS
-----------------------------------------------------------------------------------------------------------------------
1      | 2026-10-03T16:00:01.123  | EVT-1001   | JOINER   | alice.eng      | SUCCESS    | {'department': 'Engineerin...}
2      | 2026-10-03T16:00:01.456  | EVT-1002   | JOINER   | bob.fin        | SUCCESS    | {'department': 'Finance', ...}
3      | 2026-10-03T16:00:01.890  | EVT-1003   | MOVER    | alice.eng      | SUCCESS    | {'new_department': 'Sales'...}
4      | 2026-10-03T16:00:02.112  | EVT-1004   | LEAVER   | bob.fin        | SUCCESS    | {'disabled': True, 'sessio...}
5      | 2026-10-03T16:00:02.345  | EVT-1005   | JOINER   | alice.eng      | SKIPPED    | {'reason': 'Already proces...}
-----------------------------------------------------------------------------------------------------------------------
```

---

## 🔒 Security & Resilience Design

- **Least Privilege Service Account**: Authenticates via confidential client `jml-automation` using client credentials flow, scoped strictly to `realm-management` roles (`manage-users`, `view-users`, `query-users`, `view-realm`).
- **Zero-Secret Leakage**: Passwords, tokens, and secrets are strictly excluded from logs, database tables, and console output.
- **Idempotency Locks**: PostgreSQL `processed_events` table enforces primary key uniqueness on `event_id` to block duplicate feed execution.
- **Exponential Backoff**: Transients 5xx network failures are retried (max 3 retries), while 4xx errors fail fast without retrying.

---

## 🧪 Testing Suite

Execute the mock-backed unit test suite without requiring Docker containers:

```bash
python -m pytest tests/ -v
```

Test coverage includes:
- [x] Joiner user provisioning, attribute assignment, and role mapping.
- [x] Joiner idempotency duplicate event skipping.
- [x] Mover differential role reconciliation (`want - have`, `have - want`).
- [x] Leaver account deactivation, session logout, and role stripping.
- [x] Unknown user handling and input schema validation failures.
- [x] Dry-run state isolation.
- [x] Secret masking in audit logger.
- [x] KeycloakAdmin retry logic on 5xx vs fast fail on 4xx.
- [x] CSV file parsing.

---

## 📁 Repository Structure

```
jml-automation/
├── .env.example               # Template environment variables
├── .gitignore                  # Security & cache git ignore rules
├── docker-compose.yml          # Container configuration (Keycloak 26 + Postgres 16)
├── README.md                   # Project documentation & overview
├── docs/                       # Project engineering documentation
│   ├── prd.md                  # Product Requirement Document
│   ├── architecture.md         # System Architecture & Flow Diagrams
│   ├── rules.md                # Security, Code, & Testing Rules
│   ├── design.md               # Technical Design Specifications
│   ├── task.md                 # Phased Implementation Checklist
│   └── memory.md               # Knowledge Base & Decisions Record
├── keycloak/
│   └── realm-company.json      # Keycloak auto-import realm config
├── sql/
│   └── schema.sql              # PostgreSQL database initialization script
├── jml/                        # Core Python Automation Package
│   ├── __init__.py             # Package init
│   ├── __main__.py             # CLI entrypoint (run, report, check)
│   ├── config.py               # Environment configuration loader
│   ├── keycloak_client.py      # Keycloak REST API wrapper & retries
│   ├── policy.py               # Department & Role mapping policy engine
│   ├── audit.py                # PostgreSQL JSONB audit logger
│   └── processor.py            # JML event handler workflow engine
├── data/
│   └── events.csv              # Test HR event dataset feed
├── scripts/
│   └── demo.sh                 # End-to-End CLI demo script
└── tests/
    └── test_jml.py             # Pytest unit test suite
```

---

## 🔗 Project Documentation Links
- [Product Requirement Document (PRD)](docs/prd.md)
- [System Architecture](docs/architecture.md)
- [Engineering Rules & DoD](docs/rules.md)
- [Technical Design Specifications](docs/design.md)
- [Task Tracking Checklist](docs/task.md)
- [Project Memory & Decisions](docs/memory.md)

---

## 📸 Portfolio Demo Screenshots List
- `01-keycloak-before.png`: Initial Keycloak realm configuration.
- `02-dry-run.png`: CLI output executing `--dry-run` simulation.
- `03-run.png`: CLI output executing live batch event processing.
- `04-keycloak-after.png`: Keycloak Admin Console showing provisioned and modified users.
- `05-audit-report.png`: CLI output executing `python -m jml report`.
- `06-idempotent-rerun.png`: CLI output demonstrating `SKIPPED` status on duplicate event feed rerun.

---

## 🤝 How This Connects to My IAM & RBAC Project
This JML Automation project directly complements my earlier **IAM & RBAC Portfolio Project**. While the RBAC project established the `company` realm structure and client authentication flow (`company-app`), this automation engine automates the entire lifecycle of users logging into that system—provisioning new hires, updating department roles on promotion, and instantly cutting off access upon termination.

---

## 💡 What I Learned
*(User section to record personal reflections and takeaways)*
- Deepened understanding of Keycloak Admin REST APIs and client credentials authentication.
- Mastered role reconciliation math and idempotent event processing patterns in Python.
- Designed structured JSONB audit logging pipelines with PostgreSQL.
