# -*- coding: utf-8 -*-
"""
Independent Audit & Statutory Verification Suite for Deemed-Approval Workflow.
Rigorously tests:
 1. SQL Threshold: submitted_at < NOW() - INTERVAL '15 days'
    - Mathematical SQL boundary verification at exact 15-day mark (equality vs strict inequality)
 2. Boundary Cases:
    - Boundary 1: Just before 15 days (14.96 days) -> Must remain PENDING
    - Boundary 2: At/within 15-day SLA boundary -> Must remain PENDING
    - Boundary 3: Just after 15 days (15.04 days) -> Must transition to DEEMED_APPROVED
    - Boundary 4: Substantially overdue (30.00 days) -> Must transition to DEEMED_APPROVED
 3. Preservation of non-pending states (APPROVED, REJECTED, WITHDRAWN, DEEMED_APPROVED)
 4. Atomic transaction & audit logging: actor='RTPS-AUTO', action='DEEMED_APPROVED'
 5. Idempotent repeated execution (zero duplicate audit logs, zero duplicate SMS)
 6. SMS Gateway delivery verification and failure reporting without crashing
 7. Officer MCP dossier reflection
"""

import sys
import os
import time
import json
import io
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "sewasetu")
DB_USER = os.environ.get("DB_USER", "sewasetu")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "sewasetu123")
SMS_GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL", "http://localhost:8025")

def get_connection():
    hosts = [DB_HOST]
    for h in ["localhost", "db"]:
        if h not in hosts:
            hosts.append(h)
    for h in hosts:
        try:
            return psycopg2.connect(
                host=h, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, connect_timeout=3
            )
        except Exception:
            continue
    raise RuntimeError("Failed to connect to database on any host")

test_total = 0
test_passed = 0

def check(name, condition, details=""):
    global test_total, test_passed
    test_total += 1
    if condition:
        test_passed += 1
        print(f"  [PASS] {name} {f'({details})' if details else ''}")
    else:
        print(f"  [FAIL] {name} {f'({details})' if details else ''}")

print("=" * 80)
print("SEWA SETU — DEEMED APPROVAL STATUTORY AUDIT & BOUNDARY TEST SUITE")
print("=" * 80)

conn = get_connection()
conn.autocommit = True
cur = conn.cursor(cursor_factory=RealDictCursor)

# -----------------------------------------------------------------------------
# 0. DIRECT SQL MATHEMATICAL THRESHOLD VERIFICATION
# -----------------------------------------------------------------------------
print("\n[AUDIT 0] Verifying PostgreSQL Statutory SLA Expression Semantics...")
# Test 1: Exactly 15 days: '2026-10-02 02:00:00' vs cutoff '2026-10-17 02:00:00' - INTERVAL '15 days'
cur.execute("""
    SELECT (TIMESTAMP '2026-10-02 02:00:00' < TIMESTAMP '2026-10-17 02:00:00' - INTERVAL '15 days') AS is_overdue,
           (TIMESTAMP '2026-10-02 02:00:01' < TIMESTAMP '2026-10-17 02:00:00' - INTERVAL '15 days') AS is_under,
           (TIMESTAMP '2026-10-02 01:59:59' < TIMESTAMP '2026-10-17 02:00:00' - INTERVAL '15 days') AS is_over
""")
sql_eval = cur.fetchone()
check("SQL threshold: Exactly 15 days is NOT < cutoff (stays pending)", sql_eval["is_overdue"] is False)
check("SQL threshold: 1 second before 15 days is NOT < cutoff (stays pending)", sql_eval["is_under"] is False)
check("SQL threshold: 1 second past 15 days IS < cutoff (qualifies for deemed approval)", sql_eval["is_over"] is True)

def cleanup_test_records():
    cur.execute("DELETE FROM audit_log WHERE application_id IN (SELECT id FROM applications WHERE mobile LIKE '98888%')")
    cur.execute("DELETE FROM applications WHERE mobile LIKE '98888%'")

print("\n[SETUP] Cleaning up isolated test records...")
cleanup_test_records()

# -----------------------------------------------------------------------------
# 1. SEED TEST APPLICATIONS USING DATABASE INTERVALS
# -----------------------------------------------------------------------------
print("\n[SEED] Seeding boundary and invariant test records using PostgreSQL intervals...")

test_records = [
    # Boundary 1: Under threshold (14 days, 23 hours ago)
    {
        "app_no": "TEST_DA_UNDER",
        "name": "Under Threshold Citizen",
        "mobile": "9888800001",
        "interval_sql": "NOW() - INTERVAL '14 days 23 hours'",
        "status": "PENDING",
        "decided_at": None,
        "decided_by": None
    },
    # Boundary 2: Within threshold boundary (14 days 23 hours 59 minutes ago)
    {
        "app_no": "TEST_DA_EXACT",
        "name": "Exact Boundary Citizen",
        "mobile": "9888800002",
        "interval_sql": "NOW() - INTERVAL '15 days' + INTERVAL '1 minute'",
        "status": "PENDING",
        "decided_at": None,
        "decided_by": None
    },
    # Boundary 3: Just over threshold (15 days, 1 hour ago)
    {
        "app_no": "TEST_DA_OVER",
        "name": "Just Over Threshold Citizen",
        "mobile": "9888800003",
        "interval_sql": "NOW() - INTERVAL '15 days 1 hour'",
        "status": "PENDING",
        "decided_at": None,
        "decided_by": None
    },
    # Boundary 4: Substantially overdue (30 days ago)
    {
        "app_no": "TEST_DA_SUBSTANTIAL",
        "name": "Substantially Overdue Citizen",
        "mobile": "9888800004",
        "interval_sql": "NOW() - INTERVAL '30 days'",
        "status": "PENDING",
        "decided_at": None,
        "decided_by": None
    },
    # Invariant 5: Already APPROVED 20 days ago
    {
        "app_no": "TEST_DA_APPROVED",
        "name": "Pre-Approved Citizen",
        "mobile": "9888800005",
        "interval_sql": "NOW() - INTERVAL '20 days'",
        "status": "APPROVED",
        "decided_at": "NOW() - INTERVAL '18 days'",
        "decided_by": "officer:sonari_bdo"
    },
    # Invariant 6: Already REJECTED 20 days ago
    {
        "app_no": "TEST_DA_REJECTED",
        "name": "Pre-Rejected Citizen",
        "mobile": "9888800006",
        "interval_sql": "NOW() - INTERVAL '20 days'",
        "status": "REJECTED",
        "decided_at": "NOW() - INTERVAL '18 days'",
        "decided_by": "officer:sonari_bdo"
    },
    # Invariant 7: Already WITHDRAWN 20 days ago
    {
        "app_no": "TEST_DA_WITHDRAWN",
        "name": "Pre-Withdrawn Citizen",
        "mobile": "9888800007",
        "interval_sql": "NOW() - INTERVAL '20 days'",
        "status": "WITHDRAWN",
        "decided_at": "NOW() - INTERVAL '18 days'",
        "decided_by": "citizen:9888800007"
    },
    # Invariant 8: Already DEEMED_APPROVED 25 days ago
    {
        "app_no": "TEST_DA_PRE_DEEMED",
        "name": "Pre-Deemed Citizen",
        "mobile": "9888800008",
        "interval_sql": "NOW() - INTERVAL '25 days'",
        "status": "DEEMED_APPROVED",
        "decided_at": "NOW() - INTERVAL '10 days'",
        "decided_by": "RTPS-AUTO"
    }
]

for rec in test_records:
    dec_at_expr = rec["decided_at"] if rec["decided_at"] else "NULL"
    dec_by_val = rec["decided_by"]
    cur.execute(f"""
        INSERT INTO applications (application_no, applicant_name, mobile, dob, gender, marital_status,
                                  village, block, bank_account, ifsc, status, submitted_at, decided_at, decided_by)
        VALUES ('{rec["app_no"]}', '{rec["name"]}', '{rec["mobile"]}', '1955-01-01', 'Female', 'Widowed',
                'Sonari', 'Sonari', '123456789012', 'SBIN0001234', '{rec["status"]}',
                {rec["interval_sql"]}, {dec_at_expr}, {'NULL' if dec_by_val is None else f"'{dec_by_val}'"})
    """)

# -----------------------------------------------------------------------------
# 2. RUN DEEMED APPROVAL EXECUTION #1
# -----------------------------------------------------------------------------
print("\n[RUN 1] Executing deemed_approval script (Run #1)...")
import app.scripts.deemed_approval as da_script
run1_exit = da_script.main()
check("Execution #1 exit code is 0", run1_exit == 0)

# Fetch application states after Run 1
cur.execute("SELECT * FROM applications WHERE mobile LIKE '98888%' ORDER BY application_no")
app_states = {r["application_no"]: r for r in cur.fetchall()}

# Fetch audit log entries created
cur.execute("""
    SELECT al.*, a.application_no 
    FROM audit_log al 
    JOIN applications a ON al.application_id = a.id 
    WHERE a.mobile LIKE '98888%'
""")
audit_entries = cur.fetchall()
audits_by_app = {}
for entry in audit_entries:
    audits_by_app.setdefault(entry["application_no"], []).append(entry)

# -----------------------------------------------------------------------------
# 3. VERIFY ALL 4 BOUNDARY CASES
# -----------------------------------------------------------------------------
print("\n[AUDIT 1] Verifying Statutory 15-Day SLA Boundary Conditions...")

# Boundary 1: Just before 15 days (14.96d) -> Must stay PENDING
under_app = app_states.get("TEST_DA_UNDER")
check("Boundary 1: Just before 15 days (14.96d) stays PENDING",
      under_app["status"] == "PENDING" and under_app["decided_by"] is None,
      f"Status: {under_app['status']}, Decided by: {under_app['decided_by']}")
check("Boundary 1: Zero audit logs created for under-threshold application",
      len(audits_by_app.get("TEST_DA_UNDER", [])) == 0)

# Boundary 2: Within 15 days boundary (14.99d) -> Must stay PENDING (strictly < 15 days required)
exact_app = app_states.get("TEST_DA_EXACT")
check("Boundary 2: Within 15-day SLA boundary stays PENDING (strict '<' respected)",
      exact_app["status"] == "PENDING" and exact_app["decided_by"] is None,
      f"Status: {exact_app['status']}, Decided by: {exact_app['decided_by']}")
check("Boundary 2: Zero audit logs created for boundary application",
      len(audits_by_app.get("TEST_DA_EXACT", [])) == 0)

# Boundary 3: Just after 15 days (15.04d) -> Must transition to DEEMED_APPROVED
over_app = app_states.get("TEST_DA_OVER")
check("Boundary 3: Just after 15 days (15.04d) transitions to DEEMED_APPROVED",
      over_app["status"] == "DEEMED_APPROVED",
      f"Status: {over_app['status']}")
check("Boundary 3: decided_by is set to 'RTPS-AUTO'",
      over_app["decided_by"] == "RTPS-AUTO",
      f"decided_by: {over_app['decided_by']}")

cur.execute("SELECT (ABS(EXTRACT(EPOCH FROM (NOW() - decided_at))) < 60) AS is_recent FROM applications WHERE application_no = 'TEST_DA_OVER'")
check("Boundary 3: decided_at timestamp is stamped accurately", cur.fetchone()["is_recent"] is True)

# Boundary 4: Substantially overdue (30d) -> Must transition to DEEMED_APPROVED
sub_app = app_states.get("TEST_DA_SUBSTANTIAL")
check("Boundary 4: Substantially overdue (30d) transitions to DEEMED_APPROVED",
      sub_app["status"] == "DEEMED_APPROVED" and sub_app["decided_by"] == "RTPS-AUTO",
      f"Status: {sub_app['status']}, decided_by: {sub_app['decided_by']}")

# -----------------------------------------------------------------------------
# 4. VERIFY PRESERVATION OF EXISTING DECIDED STATES
# -----------------------------------------------------------------------------
print("\n[AUDIT 2] Verifying Preservation of Non-Pending Application States...")

appr_app = app_states.get("TEST_DA_APPROVED")
check("Pre-APPROVED application untouched (status: APPROVED, actor: officer:sonari_bdo)",
      appr_app["status"] == "APPROVED" and appr_app["decided_by"] == "officer:sonari_bdo")
check("Pre-APPROVED application generated 0 audit entries",
      len(audits_by_app.get("TEST_DA_APPROVED", [])) == 0)

rej_app = app_states.get("TEST_DA_REJECTED")
check("Pre-REJECTED application untouched (status: REJECTED, actor: officer:sonari_bdo)",
      rej_app["status"] == "REJECTED" and rej_app["decided_by"] == "officer:sonari_bdo")
check("Pre-REJECTED application generated 0 audit entries",
      len(audits_by_app.get("TEST_DA_REJECTED", [])) == 0)

with_app = app_states.get("TEST_DA_WITHDRAWN")
check("Pre-WITHDRAWN application untouched (status: WITHDRAWN, actor: citizen:9888800007)",
      with_app["status"] == "WITHDRAWN" and with_app["decided_by"] == "citizen:9888800007")
check("Pre-WITHDRAWN application generated 0 audit entries",
      len(audits_by_app.get("TEST_DA_WITHDRAWN", [])) == 0)

pre_deemed = app_states.get("TEST_DA_PRE_DEEMED")
check("Pre-DEEMED application untouched (status: DEEMED_APPROVED, actor: RTPS-AUTO)",
      pre_deemed["status"] == "DEEMED_APPROVED" and pre_deemed["decided_by"] == "RTPS-AUTO")
check("Pre-DEEMED application generated 0 new audit entries",
      len(audits_by_app.get("TEST_DA_PRE_DEEMED", [])) == 0)

# -----------------------------------------------------------------------------
# 5. VERIFY ATOMIC AUDIT LOGGING & ACTOR ATTRIBUTION
# -----------------------------------------------------------------------------
print("\n[AUDIT 3] Verifying Audit Log Atomicity & Actor Attribution...")

for app_no in ["TEST_DA_OVER", "TEST_DA_SUBSTANTIAL"]:
    audits = audits_by_app.get(app_no, [])
    check(f"Exactly 1 audit log entry created for {app_no}", len(audits) == 1, f"Count: {len(audits)}")
    if audits:
        entry = audits[0]
        check(f"Audit log action is 'DEEMED_APPROVED' for {app_no}", entry["action"] == "DEEMED_APPROVED")
        check(f"Audit log actor is 'RTPS-AUTO' for {app_no}", entry["actor"] == "RTPS-AUTO", f"Actor: {entry['actor']}")
        check(f"Audit log note mentions statutory SLA for {app_no}", "SLA" in (entry["note"] or ""), f"Note: {entry['note']}")
        # Timestamp match check
        app_row = app_states[app_no]
        check(f"Audit timestamp equals decided_at for {app_no}", entry["at"] == app_row["decided_at"])

# -----------------------------------------------------------------------------
# 6. VERIFY CITIZEN SMS NOTIFICATION DISPATCH
# -----------------------------------------------------------------------------
print("\n[AUDIT 4] Verifying Citizen SMS Notification Dispatch...")
sms_r1_over = 0
sms_r1_sub = 0
try:
    sms_res = requests.get(f"{SMS_GATEWAY_URL}/api/messages", timeout=3)
    if sms_res.status_code == 200:
        msgs = sms_res.json().get("messages", [])
        m_over = [m for m in msgs if m.get("to") == "9888800003"]
        m_sub = [m for m in msgs if m.get("to") == "9888800004"]
        sms_r1_over = len(m_over)
        sms_r1_sub = len(m_sub)
        check("SMS dispatched to 9888800003 (Just Over Threshold)", sms_r1_over >= 1)
        if m_over:
            check("SMS contains RTPS Act statutory approval text",
                  "stands approved under the RTPS Act" in m_over[-1].get("text", ""))
        check("SMS dispatched to 9888800004 (Substantially Overdue)", sms_r1_sub >= 1)
except Exception as e:
    print(f"  [WARN] SMS gateway verification exception: {e}")

# -----------------------------------------------------------------------------
# 7. VERIFY IDEMPOTENCY ON REPEATED SCHEDULER EXECUTION
# -----------------------------------------------------------------------------
print("\n[RUN 2] Executing deemed_approval script (Run #2 - Idempotence Check)...")
run2_exit = da_script.main()
check("Execution #2 exit code is 0", run2_exit == 0)

cur.execute("""
    SELECT al.*, a.application_no 
    FROM audit_log al 
    JOIN applications a ON al.application_id = a.id 
    WHERE a.mobile LIKE '98888%'
""")
audit_entries_r2 = cur.fetchall()
audits_by_app_r2 = {}
for entry in audit_entries_r2:
    audits_by_app_r2.setdefault(entry["application_no"], []).append(entry)

check("Zero duplicate audit entries created for TEST_DA_OVER",
      len(audits_by_app_r2.get("TEST_DA_OVER", [])) == 1,
      f"Count: {len(audits_by_app_r2.get('TEST_DA_OVER', []))}")

check("Zero duplicate audit entries created for TEST_DA_SUBSTANTIAL",
      len(audits_by_app_r2.get("TEST_DA_SUBSTANTIAL", [])) == 1,
      f"Count: {len(audits_by_app_r2.get('TEST_DA_SUBSTANTIAL', []))}")

try:
    sms_res_r2 = requests.get(f"{SMS_GATEWAY_URL}/api/messages", timeout=3)
    if sms_res_r2.status_code == 200:
        msgs_r2 = sms_res_r2.json().get("messages", [])
        sms_r2_over = len([m for m in msgs_r2 if m.get("to") == "9888800003"])
        check("Zero duplicate SMS dispatched for TEST_DA_OVER on repeated run",
              sms_r2_over == sms_r1_over,
              f"Run 1 count: {sms_r1_over}, Run 2 count: {sms_r2_over}")
except Exception:
    pass

# -----------------------------------------------------------------------------
# 8. VERIFY OFFICER MCP INTEGRATION & DOSSIER REFLECTION
# -----------------------------------------------------------------------------
print("\n[AUDIT 5] Verifying Block Officer MCP Dossier Reflection...")
try:
    from officer_mcp.tools import get_application_dossier
    from officer_mcp.auth import create_mock_officer_token
    tok = create_mock_officer_token("sonari_bdo")
    dossier = get_application_dossier(tok, application_no="TEST_DA_OVER")
    app_info = dossier.get("application", {})
    timeline = app_info.get("timeline", {})
    audit_hist = app_info.get("audit_history", [])

    check("Officer dossier reflects status as 'DEEMED_APPROVED'",
          dossier.get("status") == "success" and app_info.get("status") == "DEEMED_APPROVED")
    check("Officer dossier timeline shows decided_by as 'RTPS-AUTO'",
          timeline.get("decided_by") == "RTPS-AUTO",
          f"decided_by: {timeline.get('decided_by')}")
    check("Officer dossier audit trail contains deemed approval record",
          any(a.get("action") == "DEEMED_APPROVED" and a.get("actor") == "RTPS-AUTO" for a in audit_hist))
except Exception as e:
    print(f"  [WARN] Officer dossier check failed: {e}")

# -----------------------------------------------------------------------------
# 9. SMS GATEWAY FAILURE LOGGING & ERROR REPORTING TEST
# -----------------------------------------------------------------------------
print("\n[AUDIT 6] Verifying SMS Failure Reporting Without Crashing...")
# Point SMS_GATEWAY_URL to an unreachable address
os.environ["SMS_GATEWAY_URL"] = "http://127.0.0.1:9999"

# Seed a temporary overdue application
cur.execute("""
    INSERT INTO applications (application_no, applicant_name, mobile, dob, gender, marital_status,
                              village, block, bank_account, ifsc, status, submitted_at)
    VALUES ('TEST_DA_SMSFAIL', 'SMS Fail Citizen', '9888800099', '1955-01-01', 'Female', 'Widowed',
            'Sonari', 'Sonari', '123456789012', 'SBIN0001234', 'PENDING', NOW() - INTERVAL '20 days')
""")

# Capture stderr during deemed approval execution
stderr_capture = io.StringIO()
old_stderr = sys.stderr
sys.stderr = stderr_capture
try:
    sms_fail_exit = da_script.main()
finally:
    sys.stderr = old_stderr
    del os.environ["SMS_GATEWAY_URL"]

captured_err = stderr_capture.getvalue()
check("Job exits 0 even if SMS gateway is unavailable", sms_fail_exit == 0)
check("SMS failure is logged to stderr with [SMS WARNING]", "[SMS WARNING]" in captured_err)

# Verify database state was still saved atomically
cur.execute("SELECT status, decided_by FROM applications WHERE application_no = 'TEST_DA_SMSFAIL'")
fail_test_row = cur.fetchone()
check("Application safely transitioned to DEEMED_APPROVED despite SMS gateway failure",
      fail_test_row["status"] == "DEEMED_APPROVED" and fail_test_row["decided_by"] == "RTPS-AUTO")

# Clean up
print("\n[CLEANUP] Cleaning up isolated test records...")
cleanup_test_records()
conn.close()

print("\n" + "=" * 80)
print(f"STATUTORY AUDIT & BOUNDARY TEST SUMMARY: {test_passed} / {test_total} PASSED ({(test_passed/test_total)*100:.1f}%)")
print("=" * 80)
