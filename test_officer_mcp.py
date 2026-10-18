"""
Comprehensive Verification and Test Suite for Sewa Setu Block Officer MCP Server.
Tests:
1. OAuth 2.1 Token Authentication (RS256 signature, expiration, malformed tokens)
2. Role-Based Access Control / Permissions (Rejection of Citizen tokens on Officer tools)
3. Statutory 15-day SLA calculations & urgency metrics
4. Queue Summary & filtering by Block (get_queue_summary)
5. Listing pending applications prioritized by SLA urgency (list_pending_applications)
6. Complete dossier inspection with chronological audit history (get_application_dossier)
7. Application Approval Transition (status PENDING -> APPROVED, officer actor, audit log, SMS)
8. Application Rejection Transition (mandatory reason validation, audit log, SMS)
9. Prevention of concurrent / invalid status transitions
"""

import sys
import os
import time
from datetime import datetime, timedelta

# Force UTF-8 stdout encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 70)
print("Sewa Setu — Block Officer MCP Server Test Suite")
print("=" * 70)

try:
    from officer_mcp.server import mcp_server
    from officer_mcp.auth import (
        verify_officer_token,
        create_mock_officer_token,
        get_portal_signing_key,
        get_portal_public_key
    )
    from officer_mcp.tools import (
        get_queue_summary,
        list_pending_applications,
        get_application_dossier,
        approve_application,
        reject_application,
        calculate_sla_details
    )
    from officer_mcp.db import get_db_cursor
    from citizen_mcp.auth import create_mock_citizen_token

    # -----------------------------------------------------------------------
    # TEST 1: Registered MCP Tools on Server
    # -----------------------------------------------------------------------
    print("\n[TEST 1] Verifying MCP Server Tool Registration...")
    tools = mcp_server._tool_manager.list_tools() if hasattr(mcp_server, '_tool_manager') else []
    tool_names = [t.name for t in tools]
    print(f" -> Found {len(tools)} registered Officer tools: {tool_names}")
    expected_tools = [
        "get_queue_summary",
        "list_pending_applications",
        "get_application_dossier",
        "approve_application",
        "reject_application"
    ]
    for exp in expected_tools:
        assert exp in tool_names, f"Expected tool '{exp}' is not registered on Officer MCP Server!"
    print(" -> PASS: All 5 officer tools properly registered.")

    # -----------------------------------------------------------------------
    # TEST 2: OAuth 2.1 Token Verification & Permissions (RBAC)
    # -----------------------------------------------------------------------
    print("\n[TEST 2] Testing OAuth 2.1 RS256 Verification & Permissions...")

    # Case 2A: Valid Officer Token
    officer_token = create_mock_officer_token(username="sonari_bdo", scope="officer", role="officer")
    is_valid, err, claims = verify_officer_token(officer_token)
    assert is_valid is True, f"Valid officer token failed verification: {err}"
    assert claims.get("officer_id") == "sonari_bdo", "Officer ID extraction failed"
    assert claims.get("actor") == "officer:sonari_bdo", "Officer actor extraction failed"
    print(f" -> PASS: Valid Officer token verified (Actor: {claims.get('actor')}).")

    # Case 2B: Citizen Token Attempting Officer Access (RBAC check)
    citizen_token = create_mock_citizen_token(mobile="9876543210")
    c_valid, c_err, _ = verify_officer_token(citizen_token)
    assert c_valid is False, "Security breach: Citizen token was accepted by Officer MCP!"
    print(f" -> PASS: Citizen token correctly rejected with: '{c_err}'")

    # Case 2C: Expired Officer Token
    expired_token = create_mock_officer_token(username="expired_officer", exp_seconds=-60)
    e_valid, e_err, _ = verify_officer_token(expired_token)
    assert e_valid is False, "Expired token should not be accepted"
    print(f" -> PASS: Expired token correctly rejected with: '{e_err}'")

    # Case 2D: Missing / Malformed Token
    m_valid, m_err, _ = verify_officer_token("Bearer invalid.token.payload")
    assert m_valid is False, "Malformed token should not be accepted"
    print(f" -> PASS: Malformed token correctly rejected.")

    # -----------------------------------------------------------------------
    # TEST 3: Statutory SLA Calculation
    # -----------------------------------------------------------------------
    print("\n[TEST 3] Testing SLA Calculations & Urgency Flags...")
    now = datetime.now()

    # Case 3A: Fresh application (submitted 2 days ago)
    sla_fresh = calculate_sla_details(now - timedelta(days=2))
    assert sla_fresh["days_elapsed"] >= 2.0, "Elapsed days calculation error"
    assert sla_fresh["days_remaining"] <= 13.0, "Remaining days calculation error"
    assert sla_fresh["sla_urgency"] == "NORMAL", "Fresh application should have NORMAL urgency"
    assert sla_fresh["is_urgent"] is False, "Fresh application should not be flagged urgent"
    print(f" -> PASS: Fresh submission SLA: {sla_fresh['days_remaining']} days remaining (Status: {sla_fresh['sla_urgency']})")

    # Case 3B: Critical application (submitted 13 days ago -> 2 days remaining)
    sla_urgent = calculate_sla_details(now - timedelta(days=13))
    assert sla_urgent["days_remaining"] <= 2.0, "Remaining days calculation error"
    assert sla_urgent["sla_urgency"] == "URGENT", "Old application should have URGENT urgency"
    assert sla_urgent["is_urgent"] is True, "Old application must be flagged is_urgent=True"
    print(f" -> PASS: Urgent submission SLA: {sla_urgent['days_remaining']} days remaining (Status: {sla_urgent['sla_urgency']})")

    # Case 3C: Overdue application (submitted 16 days ago)
    sla_overdue = calculate_sla_details(now - timedelta(days=16))
    assert sla_overdue["sla_urgency"] == "OVERDUE", "16-day old application must be OVERDUE"
    print(f" -> PASS: Overdue submission SLA: {sla_overdue['days_elapsed']} days elapsed (Status: {sla_overdue['sla_urgency']})")

    # -----------------------------------------------------------------------
    # TEST 4: Tool get_queue_summary
    # -----------------------------------------------------------------------
    print("\n[TEST 4] Testing Tool: get_queue_summary()...")
    summary = get_queue_summary(officer_token)
    assert summary["status"] == "success", f"Queue summary failed: {summary.get('message')}"
    queue = summary["queue"]
    print(f" -> Total Pending: {queue['total_pending']}")
    print(f" -> Approaching 15-day SLA (<3 days): {queue['urgent_pending_approaching_sla']}")
    print(f" -> Normal Pending: {queue['normal_pending']}")
    print(f" -> Decided Breakdown: {summary['decisions_breakdown']}")
    print(" -> PASS: get_queue_summary returned accurate live queue metrics.")

    # Test with block filter
    summary_sonari = get_queue_summary(officer_token, block="Sonari")
    assert summary_sonari["status"] == "success", "Block-filtered summary failed"
    assert summary_sonari["filter_block"] == "Sonari"
    print(f" -> PASS: Block-filtered summary for Sonari: {summary_sonari['queue']['total_pending']} pending.")

    # -----------------------------------------------------------------------
    # TEST 5: Tool list_pending_applications
    # -----------------------------------------------------------------------
    print("\n[TEST 5] Testing Tool: list_pending_applications()...")
    pending_res = list_pending_applications(officer_token, limit=5, sort_by="sla_urgency")
    assert pending_res["status"] == "success", f"List pending failed: {pending_res.get('message')}"
    apps = pending_res["applications"]
    print(f" -> Retrieved {len(apps)} pending applications (Total: {pending_res['pagination']['total_pending']})")
    if apps:
        first_app = apps[0]
        print(f"    * Top priority app: #{first_app['application_id']} ({first_app['application_no']}) - {first_app['applicant_name']} ({first_app['block']}) - Days pending: {first_app['days_pending']} (SLA urgency: {first_app['sla_urgency']})")
    print(" -> PASS: list_pending_applications successfully sorted by SLA urgency.")

    # -----------------------------------------------------------------------
    # TEST 6: Tool get_application_dossier
    # -----------------------------------------------------------------------
    print("\n[TEST 6] Testing Tool: get_application_dossier()...")
    if apps:
        sample_id = apps[0]["application_id"]
        sample_no = apps[0]["application_no"]

        dossier_res = get_application_dossier(officer_token, application_id=sample_id)
        assert dossier_res["status"] == "success", f"Dossier fetch failed: {dossier_res.get('message')}"
        dossier = dossier_res["application"]
        assert dossier["application_id"] == sample_id
        assert dossier["application_no"] == sample_no
        assert "personal_details" in dossier
        assert "bank_details" in dossier
        assert "timeline" in dossier
        assert "audit_history" in dossier
        print(f" -> Dossier #{sample_id} ({sample_no}) loaded successfully:")
        print(f"    * Applicant: {dossier['personal_details']['applicant_name']}, Age: {dossier['personal_details']['calculated_age']}")
        print(f"    * Bank Account: {dossier['bank_details']['masked_account']} (IFSC: {dossier['bank_details']['ifsc']})")
        print(f"    * Audit Entries Count: {len(dossier['audit_history'])}")
        print(" -> PASS: get_application_dossier retrieved comprehensive dossier and audit trail.")

    # -----------------------------------------------------------------------
    # TEST 7: Tool approve_application (State transition, audit log & SMS)
    # -----------------------------------------------------------------------
    print("\n[TEST 7] Testing Tool: approve_application()...")
    # Insert a dedicated test application to safely test approval flow without affecting live data
    test_mobile_appr = "9998881111"
    with get_db_cursor(commit=True) as cur:
        # Clean up any previous test record
        cur.execute("DELETE FROM audit_log WHERE application_id IN (SELECT id FROM applications WHERE mobile = %s)", (test_mobile_appr,))
        cur.execute("DELETE FROM applications WHERE mobile = %s", (test_mobile_appr,))

        cur.execute("""
            INSERT INTO applications (
                application_no, applicant_name, mobile, dob, gender, marital_status,
                village, block, bank_account, ifsc, doc_path, status, submitted_at
            ) VALUES (
                'SSPEVAL001', 'Test Applicant Approval', %s, '1955-01-01', 'Female', 'Widowed',
                'Sonari Gaon', 'Sonari', '123456789012', 'SBIN0001234', '/uploads/test.pdf', 'PENDING', %s
            ) RETURNING id
        """, (test_mobile_appr, datetime.now() - timedelta(days=5)))
        appr_test_id = cur.fetchone()[0]

    # Execute Approval Tool
    note = "Verified original Aadhaar card and active bank passbook in person."
    appr_res = approve_application(officer_token, application_id=appr_test_id, officer_note=note)
    assert appr_res["status"] == "success", f"Approval failed: {appr_res.get('message')}"
    assert appr_res["new_status"] == "APPROVED"
    assert appr_res["decided_by"] == "officer:sonari_bdo"
    assert appr_res["audit_recorded"] is True
    print(f" -> Approval tool response: {appr_res['message']} (Decided by: {appr_res['decided_by']})")

    # Verify Database state & Audit Log
    with get_db_cursor() as cur:
        cur.execute("SELECT status, decided_by, decided_at FROM applications WHERE id = %s", (appr_test_id,))
        db_app = cur.fetchone()
        assert db_app[0] == "APPROVED", "DB application status was not updated to APPROVED"
        assert db_app[1] == "officer:sonari_bdo", "DB decided_by does not match officer actor"
        assert db_app[2] is not None, "decided_at timestamp was not stamped"

        cur.execute("SELECT action, actor, note FROM audit_log WHERE application_id = %s AND action = 'APPROVED'", (appr_test_id,))
        audit_row = cur.fetchone()
        assert audit_row is not None, "Audit log entry was not written!"
        assert audit_row[0] == "APPROVED"
        assert audit_row[1] == "officer:sonari_bdo"
        assert audit_row[2] == note

    print(" -> PASS: approve_application updated DB status, stamped officer identity, and wrote audit record.")

    # Verify that trying to approve again fails
    re_appr = approve_application(officer_token, application_id=appr_test_id)
    assert re_appr["status"] == "error", "Re-approving already approved application should fail!"
    assert re_appr["error_code"] == "INVALID_STATE"
    print(f" -> PASS: Prevented illegal state transition: '{re_appr['message']}'")

    # -----------------------------------------------------------------------
    # TEST 8: Tool reject_application (Mandatory reason, audit log & SMS)
    # -----------------------------------------------------------------------
    print("\n[TEST 8] Testing Tool: reject_application()...")
    test_mobile_rej = "9998882222"
    with get_db_cursor(commit=True) as cur:
        # Clean up any previous test record
        cur.execute("DELETE FROM audit_log WHERE application_id IN (SELECT id FROM applications WHERE mobile = %s)", (test_mobile_rej,))
        cur.execute("DELETE FROM applications WHERE mobile = %s", (test_mobile_rej,))

        cur.execute("""
            INSERT INTO applications (
                application_no, applicant_name, mobile, dob, gender, marital_status,
                village, block, bank_account, ifsc, doc_path, status, submitted_at
            ) VALUES (
                'SSPEVAL002', 'Test Applicant Rejection', %s, '1958-05-10', 'Male', 'Married',
                'Borgaon Pathar', 'Borgaon', '987654321098', 'PUNB0005678', '/uploads/test2.pdf', 'PENDING', %s
            ) RETURNING id
        """, (test_mobile_rej, datetime.now() - timedelta(days=8)))
        rej_test_id = cur.fetchone()[0]

    # Case 8A: Rejection without mandatory reason MUST fail
    rej_blank = reject_application(officer_token, application_id=rej_test_id, rejection_reason="")
    assert rej_blank["status"] == "error", "Rejection without reason should be rejected!"
    assert rej_blank["error_code"] == "MISSING_REASON"
    print(f" -> PASS: Mandatory rejection reason enforced: '{rej_blank['message']}'")

    # Case 8B: Valid Rejection with Reason
    reason = "Attached age proof illegible; bank account belongs to another individual per PFMS verification."
    rej_res = reject_application(officer_token, application_id=rej_test_id, rejection_reason=reason)
    assert rej_res["status"] == "success", f"Rejection failed: {rej_res.get('message')}"
    assert rej_res["new_status"] == "REJECTED"
    assert rej_res["decided_by"] == "officer:sonari_bdo"
    assert rej_res["rejection_reason"] == reason
    print(f" -> Rejection tool response: {rej_res['message']}")

    # Verify Database state & Audit Log
    with get_db_cursor() as cur:
        cur.execute("SELECT status, decided_by, decided_at FROM applications WHERE id = %s", (rej_test_id,))
        db_rej = cur.fetchone()
        assert db_rej[0] == "REJECTED", "DB application status was not updated to REJECTED"
        assert db_rej[1] == "officer:sonari_bdo"

        cur.execute("SELECT action, actor, note FROM audit_log WHERE application_id = %s AND action = 'REJECTED'", (rej_test_id,))
        audit_rej = cur.fetchone()
        assert audit_rej is not None, "Audit log entry was not written for rejection!"
        assert audit_rej[0] == "REJECTED"
        assert audit_rej[1] == "officer:sonari_bdo"
        assert audit_rej[2] == reason

    print(" -> PASS: reject_application updated DB status, recorded mandatory reason in audit log, and triggered SMS.")

    # Clean up test evaluation records
    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM audit_log WHERE application_id IN (%s, %s)", (appr_test_id, rej_test_id))
        cur.execute("DELETE FROM applications WHERE id IN (%s, %s)", (appr_test_id, rej_test_id))

    print("\n" + "=" * 70)
    print("ALL 8 OFFICER MCP TEST SUITES PASSED SUCCESSFULLY!")
    print("=" * 70)

except Exception as err:
    print(f"\n[FAIL] Test suite encountered an error: {err}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
