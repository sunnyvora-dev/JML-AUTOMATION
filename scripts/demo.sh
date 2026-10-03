#!/usr/bin/env bash
set -e

echo "========================================================"
echo " JML Identity Lifecycle Automation - End-to-End Demo Script"
echo "========================================================"

echo -e "\nStep 1: Running Infrastructure Health Check..."
python -m jml check

echo -e "\nStep 2: Executing Batch in DRY-RUN Mode..."
python -m jml run --file data/events.csv --dry-run || true

echo -e "\nStep 3: Executing Live Batch Processing..."
python -m jml run --file data/events.csv --show-temp-passwords || true

echo -e "\nStep 4: Querying PostgreSQL Audit Log History..."
python -m jml report --limit 20

echo -e "\nStep 5: Executing Duplicate Batch to Demonstrate Idempotency Skipping..."
python -m jml run --file data/events.csv || true

echo -e "\n========================================================"
echo " Keycloak Console Verification Instructions:"
echo " 1. Open http://localhost:8080/admin/ (admin/admin123)"
echo " 2. Select Realm: 'company'"
echo " 3. Verify User 'alice.eng':"
echo "    - Attributes: department=Sales, employee_id=EMP-001"
echo "    - Role Mappings: [employee, sales, manager]"
echo " 4. Verify User 'bob.fin':"
echo "    - User Status: Disabled (enabled=false)"
echo "    - Attributes: leaver_date set"
echo "    - Role Mappings: Managed roles stripped"
echo "========================================================"
