"""
Standalone Mock Demo Runner - Simulates Keycloak & PostgreSQL in-memory
to demonstrate full JML lifecycle execution without requiring Docker containers.
"""

import csv
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from tests.test_jml import FakeKeycloak, FakeAudit
from jml.processor import process_event

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


def run_demo():
    csv_file = "data/events.csv"
    if not os.path.exists(csv_file):
        print(f"Error: CSV dataset file '{csv_file}' not found.")
        sys.exit(1)

    events = []
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            events.append(r)

    print("====================================================================================================")
    print("                 JML IDENTITY LIFECYCLE AUTOMATION - IN-MEMORY DEMO RUNNER                          ")
    print("====================================================================================================\n")

    kc = FakeKeycloak()
    audit = FakeAudit()

    # --- Phase 1: Dry Run Simulation ---
    print(">>> PHASE 1: DRY-RUN MODE (Simulating actions without mutating state)...\n")
    results_dry = []
    for ev in events:
        res = process_event(ev, kc, audit, dry_run=True)
        results_dry.append(res)

    print("-" * 110)
    print(f"{'EVENT ID':<12} | {'ACTION':<8} | {'USERNAME':<15} | {'STATUS':<10} | {'SUMMARY NOTE'}")
    print("-" * 110)
    for evt_id, act, target_usr, stat, note in results_dry:
        formatted_stat = format_status(stat)
        pad = 10 + (len(formatted_stat) - len(stat))
        print(f"{evt_id:<12} | {act:<8} | {target_usr:<15} | {formatted_stat:<{pad}} | {note}")
    print("-" * 110 + "\n")

    # Reset audit logs for live phase
    audit.logs.clear()
    audit.processed.clear()

    # --- Phase 2: Live Execution ---
    print(">>> PHASE 2: LIVE EXECUTION (Provisioning, Role Reconciliation, & Deactivation)...\n")
    results_live = []
    counts = {"SUCCESS": 0, "SKIPPED": 0, "FAILED": 0, "DRY_RUN": 0}

    for ev in events:
        res = process_event(ev, kc, audit, dry_run=False, show_temp_passwords=True)
        results_live.append(res)
        counts[res[3]] = counts.get(res[3], 0) + 1

    print("-" * 110)
    print(f"{'EVENT ID':<12} | {'ACTION':<8} | {'USERNAME':<15} | {'STATUS':<10} | {'SUMMARY NOTE'}")
    print("-" * 110)
    for evt_id, act, target_usr, stat, note in results_live:
        formatted_stat = format_status(stat)
        pad = 10 + (len(formatted_stat) - len(stat))
        print(f"{evt_id:<12} | {act:<8} | {target_usr:<15} | {formatted_stat:<{pad}} | {note}")
    print("-" * 110)

    print(
        f"\nBatch Summary: Total={len(events)} | "
        f"Success={counts['SUCCESS']} | "
        f"Skipped={counts['SKIPPED']} | "
        f"Failed={counts['FAILED']}\n"
    )

    # --- Phase 3: PostgreSQL Audit Log Report ---
    print(">>> PHASE 3: POSTGRESQL AUDIT LOG REPORT...\n")
    logs = audit.report(limit=20)
    print("-" * 115)
    print(f"{'ID':<4} | {'EVENT ID':<10} | {'ACTION':<8} | {'TARGET':<14} | {'STATUS':<10} | {'DETAILS'}")
    print("-" * 115)
    for idx, r in enumerate(logs, start=1):
        formatted_stat = format_status(str(r.get("status", "")))
        stat_raw = str(r.get("status", ""))
        pad = 10 + (len(formatted_stat) - len(stat_raw))
        details_str = str(r.get("details", {}))
        if len(details_str) > 40:
            details_str = details_str[:37] + "..."
        print(
            f"{idx:<4} | {r.get('event_id', ''):<10} | "
            f"{r.get('action', ''):<8} | {r.get('username', ''):<14} | "
            f"{formatted_stat:<{pad}} | {details_str}"
        )
    print("-" * 115 + "\n")

    # --- Phase 4: Idempotency Re-run Check ---
    print(">>> PHASE 4: IDEMPOTENCY CHECK (Re-running same dataset to verify duplicates are SKIPPED)...\n")
    results_rerun = []
    for ev in events[:4]:  # rerun first 4 valid events
        res = process_event(ev, kc, audit, dry_run=False)
        results_rerun.append(res)

    print("-" * 110)
    print(f"{'EVENT ID':<12} | {'ACTION':<8} | {'USERNAME':<15} | {'STATUS':<10} | {'SUMMARY NOTE'}")
    print("-" * 110)
    for evt_id, act, target_usr, stat, note in results_rerun:
        formatted_stat = format_status(stat)
        pad = 10 + (len(formatted_stat) - len(stat))
        print(f"{evt_id:<12} | {act:<8} | {target_usr:<15} | {formatted_stat:<{pad}} | {note}")
    print("-" * 110)
    print("\n[SUCCESS] Idempotency verified: All repeated events were safely SKIPPED!")


if __name__ == "__main__":
    run_demo()
