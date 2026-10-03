"""
JML Automation CLI Entrypoint - Manage identity lifecycle batch processing, reporting, and health checks.
"""

import argparse
import csv
import os
import sys
from typing import List, Dict, Any

from jml.config import Config
from jml.keycloak_client import KeycloakAdmin, KeycloakAPIError
from jml.audit import Audit
from jml.processor import process_event

# ANSI Color Codes
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_CYAN = "\033[96m"
COLOR_RESET = "\033[0m"


def colorize(text: str, color_code: str) -> str:
    if sys.stdout.isatty():
        return f"{color_code}{text}{COLOR_RESET}"
    return text


def format_status(status: str) -> str:
    s = status.upper()
    if s == "SUCCESS":
        return colorize(s, COLOR_GREEN)
    elif s in ("SKIPPED", "SKIP"):
        return colorize(s, COLOR_YELLOW)
    elif s == "FAILED":
        return colorize(s, COLOR_RED)
    elif s == "DRY_RUN":
        return colorize(s, COLOR_CYAN)
    return s


def cmd_check(cfg: Config) -> int:
    """Executes environment and connection health checks."""
    print("=== JML Automation Infrastructure & Security Health Check ===")
    has_errors = False

    # 1. Database Connectivity Check
    print("[1/3] Testing PostgreSQL database connection...")
    try:
        audit = Audit(cfg.database_url)
        if audit._conn:
            print("      [OK] PostgreSQL database connected successfully.")
        else:
            print("      [WARN] Database connection failed (fallback audit logging active).")
    except Exception as exc:
        print(f"      [ERROR] PostgreSQL connection error: {exc}")
        has_errors = True

    # 2. Keycloak REST API Connectivity & Auth Check
    print("[2/3] Testing Keycloak Admin API token authentication...")
    try:
        kc = KeycloakAdmin(
            base_url=cfg.keycloak_url,
            realm=cfg.realm,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
        )
        token = kc.get_token()
        if token:
            print("      [OK] Keycloak service account client authenticated successfully.")
    except Exception as exc:
        print(f"      [ERROR] Keycloak authentication failed: {exc}")
        has_errors = True
        return 1

    # 3. Keycloak Service Account Permission Check
    print("[3/3] Testing Keycloak service account RBAC permissions...")
    try:
        kc.find_user("non_existent_check_user")
        print("      [OK] 'view-users' and 'query-users' realm-management permissions verified.")
    except Exception as exc:
        print(f"      [ERROR] Service account permission check failed: {exc}")
        has_errors = True

    if has_errors:
        print("\nHealth check completed with errors.")
        return 1
    else:
        print("\nAll health checks passed successfully!")
        return 0


def cmd_run(args, cfg: Config) -> int:
    """Runs JML event batch execution from CSV file."""
    filepath = args.file
    if not os.path.exists(filepath):
        print(f"Error: Event CSV file '{filepath}' not found.", file=sys.stderr)
        return 1

    events: List[Dict[str, Any]] = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append(row)

    print(f"Loaded {len(events)} JML event(s) from '{filepath}'. Mode: {'DRY RUN' if args.dry_run else 'LIVE EXECUTION'}\n")

    audit = Audit(cfg.database_url)
    kc = KeycloakAdmin(
        base_url=cfg.keycloak_url,
        realm=cfg.realm,
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
    )

    results = []
    counts = {"SUCCESS": 0, "SKIPPED": 0, "FAILED": 0, "DRY_RUN": 0}

    for ev in events:
        res = process_event(
            event=ev,
            kc=kc,
            audit=audit,
            dry_run=args.dry_run,
            show_temp_passwords=args.show_temp_passwords,
        )
        results.append(res)
        counts[res[3]] = counts.get(res[3], 0) + 1

    # Output tabular results
    print("-" * 110)
    print(f"{'EVENT ID':<12} | {'ACTION':<8} | {'USERNAME':<15} | {'STATUS':<10} | {'SUMMARY NOTE'}")
    print("-" * 110)
    for evt_id, act, target_usr, stat, note in results:
        formatted_stat = format_status(stat)
        # Handle padding offset for color codes
        pad = 10 + (len(formatted_stat) - len(stat))
        print(f"{evt_id:<12} | {act:<8} | {target_usr:<15} | {formatted_stat:<{pad}} | {note}")
    print("-" * 110)

    print(
        f"\nSummary: Total={len(events)} | "
        f"Success={counts['SUCCESS']} | "
        f"Skipped={counts['SKIPPED']} | "
        f"Failed={counts['FAILED']} | "
        f"DryRun={counts['DRY_RUN']}"
    )

    audit.close()
    return 1 if counts["FAILED"] > 0 else 0


def cmd_report(args, cfg: Config) -> int:
    """Prints formatted audit log history."""
    audit = Audit(cfg.database_url)
    logs = audit.report(username=args.user, limit=args.limit)

    if not logs:
        print("No audit log records found.")
        audit.close()
        return 0

    print(f"=== JML Audit Log Report (Showing top {len(logs)} records) ===")
    print("-" * 115)
    print(f"{'ID':<6} | {'TIMESTAMP':<24} | {'EVENT ID':<10} | {'ACTION':<8} | {'TARGET':<14} | {'STATUS':<10} | {'DETAILS'}")
    print("-" * 115)

    for r in logs:
        ts_str = str(r.get("ts", ""))[:23]
        formatted_stat = format_status(str(r.get("status", "")))
        stat_raw = str(r.get("status", ""))
        pad = 10 + (len(formatted_stat) - len(stat_raw))
        details_str = str(r.get("details", {}))
        if len(details_str) > 35:
            details_str = details_str[:32] + "..."
        print(
            f"{r.get('id', ''):<6} | {ts_str:<24} | {r.get('event_id', ''):<10} | "
            f"{r.get('action', ''):<8} | {r.get('target_username', ''):<14} | "
            f"{formatted_stat:<{pad}} | {details_str}"
        )
    print("-" * 115)

    audit.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="jml",
        description="Identity Lifecycle Automation (Joiner-Mover-Leaver) for Keycloak & PostgreSQL",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Execute JML event batch from CSV feed")
    run_parser.add_argument("--file", "-f", required=True, help="Path to input CSV feed file")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate execution without modifying Keycloak")
    run_parser.add_argument(
        "--show-temp-passwords", action="store_true", help="Display generated temporary passwords to stdout (Demo mode)"
    )

    # Command: report
    report_parser = subparsers.add_parser("report", help="Display operational audit history log")
    report_parser.add_argument("--user", "-u", help="Filter audit logs by target username")
    report_parser.add_argument("--limit", "-n", type=int, default=50, help="Maximum log records to retrieve")

    # Command: check
    subparsers.add_parser("check", help="Verify infrastructure and service account health")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        cfg = Config.load_from_env()
    except Exception as exc:
        print(f"Configuration Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.command == "check":
        sys.exit(cmd_check(cfg))
    elif args.command == "run":
        sys.exit(cmd_run(args, cfg))
    elif args.command == "report":
        sys.exit(cmd_report(args, cfg))


if __name__ == "__main__":
    main()
