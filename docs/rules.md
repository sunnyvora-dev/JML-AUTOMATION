# Project Engineering & Governance Rules

## 1. Security Rules
- **Rule SEC-01 (Zero Secret Leakage)**: Passwords, bearer tokens, service account client secrets, and sensitive tokens MUST NEVER be printed to logs, written to stdout (except `--show-temp-passwords` when explicitly invoked), or stored in PostgreSQL audit `details` JSONB.
- **Rule SEC-02 (Least Privilege)**: Service account client permissions in Keycloak MUST be restricted strictly to `realm-management` scope (`manage-users`, `view-users`, `query-users`, `view-realm`). Do NOT grant master realm admin or `admin` superuser roles.
- **Rule SEC-03 (Environment-Based Configuration)**: Secret credentials MUST NOT be hardcoded in Python code or static configuration files. Read all runtime parameters from `.env` or system environment variables.
- **Rule SEC-04 (Account Retention)**: Offboarded employees MUST NOT be hard deleted from Keycloak. Always set `enabled=False` and revoke access roles to maintain audit integrity and potential account restoration capability.

## 2. Code Quality Rules
- **Rule CODE-01 (Python Compliance)**: Code must target Python 3.12 syntax, including standard library type hinting (`str`, `dict`, `list`, `Optional`, `Any`).
- **Rule CODE-02 (Modular Structure)**: Code must be clean and decoupled across modules (`config.py`, `keycloak_client.py`, `policy.py`, `audit.py`, `processor.py`, `__main__.py`).
- **Rule CODE-03 (HTTP Session & Timeouts)**: Every outgoing Keycloak API request MUST use a common `requests.Session` instance with explicit timeouts (e.g., `timeout=(3.05, 10.0)`).
- **Rule CODE-04 (Managed Roles Scoping)**: Role modification algorithms MUST strictly operate on the whitelist `MANAGED_ROLES`. System default roles (e.g., `default-roles-company`, `uma_authorization`) must remain unmodified.

## 3. Testing Rules
- **Rule TEST-01 (Deterministic Unit Testing)**: Unit tests MUST run isolated without requiring live Docker containers or external network connectivity using mock implementations (`FakeKeycloak`, `FakeAudit`).
- **Rule TEST-02 (Scenario Coverage)**: Tests MUST validate Joiner, Mover, Leaver workflows, idempotency skips, unknown users, invalid event payload schemas, dry-run safety, secret sanitization, retry handlers, and CSV parsing.

## 4. Git & Documentation Rules
- **Rule GIT-01 (Conventional Commits)**: Commit messages must follow conventional format: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- **Rule DOCS-01 (Documentation First)**: Any change in system behavior or schema must be updated in `/docs` first before implementation code is modified.

## 5. Definition of Done (DoD)
A task or release is considered complete ONLY when:
1. All 6 documentation files (`prd.md`, `architecture.md`, `rules.md`, `design.md`, `task.md`, `memory.md`) are accurate and updated.
2. `docker compose up -d` boots Keycloak and Postgres cleanly.
3. `python -m jml check` passes successfully.
4. `python -m jml run --file data/events.csv` executes all test events seamlessly.
5. `pytest` executes and passes 100% of test suites.
6. Zero passwords or secrets are detected in audit output or database tables.
