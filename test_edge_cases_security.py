# -*- coding: utf-8 -*-
"""
Comprehensive Negative, Security, and Edge-Case Test Suite for Sewa Setu.
Tests:
1. Underage applicant submission rejection
2. Malformed IFSC & invalid bank account validation
3. Duplicate active application block
4. Cross-citizen data isolation
5. Officer RBAC & scope rejection (citizen token on officer tools)
6. Illegal state transition prevention (deciding already-decided apps)
7. Mandatory rejection reason enforcement
8. SQL injection resistance
9. OAuth 2.1 RS256 signature verification & expiration enforcement
10. Sensitive data masking in traces
"""

import sys
import os
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 75)
print("Sewa Setu — Security, Reliability & Edge-Case Verification Suite")
print("=" * 75)

from citizen_mcp.tools import (
    check_eligibility,
    submit_pension_application,
    check_my_application,
    get_my_application_status,
    withdraw_pending_application
)
from citizen_mcp.auth import create_mock_citizen_token
from officer_mcp.tools import (
    get_queue_summary,
    list_pending_applications,
    get_application_dossier,
    approve_application,
    reject_application,
    calculate_sla_details
)
from officer_mcp.auth import create_mock_officer_token
from officer_mcp.db import get_db_cursor
import jwt

test_passed = 0
test_total = 0

def check(name, condition, msg=""):
    global test_passed, test_total
    test_total += 1
    if condition:
        test_passed += 1
        print(f"  [PASS] {name} {msg}")
    else:
        print(f"  [FAIL] {name} {msg}")

# ---------------------------------------------------------------------------
# TEST 1: Underage Applicants (Age < 60)
# ---------------------------------------------------------------------------
print("\n[TEST 1] Testing Underage Applicant Guardrails...")
el1 = check_eligibility("01/01/1975", "Sonari")
check("check_eligibility rejects age 51", el1["eligible"] is False and el1["calculated_age"] == 51)
check("Eligibility message specifies future eligibility year", "2035" in str(el1.get("errors", [])))

token_underage = create_mock_citizen_token("9999900001")
sub_underage = submit_pension_application(
    token_underage,
    applicant_name="Underage Test",
    dob="01/01/1975",
    gender="Male",
    marital_status="Married",
    village="Sonari",
    block="Sonari",
    bank_account="1234567890",
    ifsc="SBIN0001234"
)
check("submit_pension_application rejects underage applicant", sub_underage.get("status") in ("validation_failed", "error"))

# ---------------------------------------------------------------------------
# TEST 2: Invalid Bank & IFSC Formats
# ---------------------------------------------------------------------------
print("\n[TEST 2] Testing Bank IFSC & Account Formatting Guardrails...")
token_bank = create_mock_citizen_token("9999900002")

bad_ifsc_cases = ["SBIN00", "12345", "SBIN00000000", "SBIN9991234", "XYZ!@#"]
for bad_ifsc in bad_ifsc_cases:
    res = submit_pension_application(
        token_bank,
        applicant_name="Bank Test",
        dob="01/01/1950",
        gender="Female",
        marital_status="Widowed",
        village="Sonari",
        block="Sonari",
        bank_account="1234567890",
        ifsc=bad_ifsc
    )
    check(f"Rejects malformed IFSC '{bad_ifsc}'", res.get("status") in ("validation_failed", "error"))

bad_account_cases = ["123", "abc123456789", "123456789012345678901", ""]
for bad_acc in bad_account_cases:
    res = submit_pension_application(
        token_bank,
        applicant_name="Bank Test",
        dob="01/01/1950",
        gender="Female",
        marital_status="Widowed",
        village="Sonari",
        block="Sonari",
        bank_account=bad_acc,
        ifsc="SBIN0001234"
    )
    check(f"Rejects invalid bank account '{bad_acc}'", res.get("status") in ("validation_failed", "error"))

# ---------------------------------------------------------------------------
# TEST 3: Duplicate Active Application Invariant
# ---------------------------------------------------------------------------
print("\n[TEST 3] Testing Single Active Application Invariant...")
token_dup = create_mock_citizen_token("9999900003")

# Clean up
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE mobile = '9999900003'")

# First submission -> Success
sub1 = submit_pension_application(
    token_dup,
    applicant_name="Duplicate Test Citizen",
    dob="01/01/1950",
    gender="Female",
    marital_status="Widowed",
    village="Sonari",
    block="Sonari",
    bank_account="987654321012",
    ifsc="SBIN0001234"
)
check("First application successfully created", sub1.get("status") == "success")

# Second submission while PENDING -> Must be rejected
sub2 = submit_pension_application(
    token_dup,
    applicant_name="Duplicate Test Citizen",
    dob="01/01/1950",
    gender="Female",
    marital_status="Widowed",
    village="Sonari",
    block="Sonari",
    bank_account="987654321012",
    ifsc="SBIN0001234"
)
check("Second concurrent application blocked", sub2.get("status") == "rejected_duplicate")

# Clean up
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE mobile = '9999900003'")

# ---------------------------------------------------------------------------
# TEST 4: Cross-Citizen Data Isolation
# ---------------------------------------------------------------------------
print("\n[TEST 4] Testing Cross-Citizen Data Isolation...")
token_user_a = create_mock_citizen_token("9999900004")
token_user_b = create_mock_citizen_token("9999900005")

# Seed application for User A
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE mobile IN ('9999900004', '9999900005')")
    cur.execute("""
        INSERT INTO applications (application_no, applicant_name, mobile, dob, gender, marital_status,
                                  village, block, bank_account, ifsc, status, submitted_at)
        VALUES ('SSPXISO001', 'User A', '9999900004', '1950-01-01', 'Male', 'Married',
                'Namti', 'Namti', '111122223333', 'SBIN0001111', 'PENDING', NOW())
    """)

# User B queries check_my_application
chk_b = check_my_application(token_user_b)
check("User B cannot see User A's application", chk_b.get("has_active_application") is False)

# User B attempts to withdraw while having no application
w_b = withdraw_pending_application(token_user_b, reason="Trying to withdraw")
check("User B cannot withdraw User A's application", w_b.get("status") == "error")

# Clean up
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE mobile IN ('9999900004', '9999900005')")

# ---------------------------------------------------------------------------
# TEST 5: RBAC & Scope Enforcement (Citizen token on Officer tools)
# ---------------------------------------------------------------------------
print("\n[TEST 5] Testing RBAC: Citizen Token Rejection on Officer Tools...")
citizen_tok = create_mock_citizen_token("9999900006")

q_err = get_queue_summary(citizen_tok)
check("get_queue_summary rejects citizen token", q_err.get("status") == "error" and "AUTH" in q_err.get("error_code", ""))

list_err = list_pending_applications(citizen_tok)
check("list_pending_applications rejects citizen token", list_err.get("status") == "error")

dossier_err = get_application_dossier(citizen_tok, application_no="SSPXISO001")
check("get_application_dossier rejects citizen token", dossier_err.get("status") == "error")

appr_err = approve_application(citizen_tok, application_no="SSPXISO001")
check("approve_application rejects citizen token", appr_err.get("status") == "error")

rej_err = reject_application(citizen_tok, application_no="SSPXISO001", rejection_reason="test")
check("reject_application rejects citizen token", rej_err.get("status") == "error")

# ---------------------------------------------------------------------------
# TEST 6: Illegal State Transitions
# ---------------------------------------------------------------------------
print("\n[TEST 6] Testing Prevention of Illegal State Transitions...")
officer_tok = create_mock_officer_token("sonari_bdo")

# Seed an already approved application
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE application_no = 'SSPXDEC001'")
    cur.execute("""
        INSERT INTO applications (application_no, applicant_name, mobile, dob, gender, marital_status,
                                  village, block, bank_account, ifsc, status, submitted_at, decided_at, decided_by)
        VALUES ('SSPXDEC001', 'Decided App', '9999900007', '1950-01-01', 'Male', 'Married',
                'Sonari', 'Sonari', '111122223333', 'SBIN0001111', 'APPROVED', NOW() - INTERVAL '2 days', NOW(), 'officer:sonari_bdo')
    """)

# Attempt to re-approve
re_appr = approve_application(officer_tok, application_no="SSPXDEC001")
check("Cannot re-approve an already APPROVED application", re_appr.get("status") == "error" and "INVALID_STATE" in re_appr.get("error_code", ""))

# Attempt to reject an already approved application
re_rej = reject_application(officer_tok, application_no="SSPXDEC001", rejection_reason="Changed mind")
check("Cannot reject an already APPROVED application", re_rej.get("status") == "error" and "INVALID_STATE" in re_rej.get("error_code", ""))

# Clean up
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE application_no = 'SSPXDEC001'")

# ---------------------------------------------------------------------------
# TEST 7: Mandatory Rejection Reason
# ---------------------------------------------------------------------------
print("\n[TEST 7] Testing Mandatory Rejection Reason Enforcement...")
# Seed a pending application
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE application_no = 'SSPXREJ001'")
    cur.execute("""
        INSERT INTO applications (application_no, applicant_name, mobile, dob, gender, marital_status,
                                  village, block, bank_account, ifsc, status, submitted_at)
        VALUES ('SSPXREJ001', 'Rejection Test', '9999900008', '1950-01-01', 'Male', 'Married',
                'Namti', 'Namti', '111122223333', 'SBIN0001111', 'PENDING', NOW())
    """)

rej_empty = reject_application(officer_tok, application_no="SSPXREJ001", rejection_reason="")
check("Reject with empty string rejected", rej_empty.get("status") == "error" and rej_empty.get("error_code") in ("MISSING_REASON", "REASON_REQUIRED"))

rej_spaces = reject_application(officer_tok, application_no="SSPXREJ001", rejection_reason="   \n\t  ")
check("Reject with whitespace rejected", rej_spaces.get("status") == "error" and rej_spaces.get("error_code") in ("MISSING_REASON", "REASON_REQUIRED"))

# Clean up
with get_db_cursor(commit=True) as cur:
    cur.execute("DELETE FROM applications WHERE application_no = 'SSPXREJ001'")

# ---------------------------------------------------------------------------
# TEST 8: SQL Injection Resistance
# ---------------------------------------------------------------------------
print("\n[TEST 8] Testing SQL Injection Resistance...")
sqli_inputs = [
    "' OR '1'='1",
    "'; DROP TABLE applications; --",
    "Sonari' UNION SELECT NULL, NULL--",
    "100012 OR 1=1"
]
for sqli in sqli_inputs:
    el_sqli = check_eligibility("01/01/1950", sqli)
    check(f"check_eligibility handles SQLi payload '{sqli}'", el_sqli["eligible"] is False)

    q_sqli = get_queue_summary(officer_tok, block=sqli)
    check(f"get_queue_summary handles SQLi payload in block", q_sqli.get("status") in ("error", "success"))

# ---------------------------------------------------------------------------
# TEST 9: OAuth 2.1 Security & Token Integrity
# ---------------------------------------------------------------------------
print("\n[TEST 9] Testing OAuth 2.1 RS256 Token Integrity...")
# Expired token
now = int(time.time())
expired_claims = {
    "iss": "http://localhost:8000",
    "sub": "officer:sonari_bdo",
    "aud": "http://localhost:8002/mcp/officer",
    "scope": "officer",
    "role": "officer",
    "iat": now - 7200,
    "exp": now - 3600
}
expired_tok = jwt.encode(expired_claims, "mock-secret", algorithm="HS256")
exp_res = get_queue_summary(expired_tok)
check("Expired token rejected", exp_res.get("status") == "error" and "AUTH" in exp_res.get("error_code", ""))

# Malformed token
mal_res = get_queue_summary("Bearer not-a-valid-jwt-token")
check("Malformed token rejected", mal_res.get("status") == "error" and "AUTH" in mal_res.get("error_code", ""))

# ---------------------------------------------------------------------------
# TEST 10: Masking of Sensitive Data
# ---------------------------------------------------------------------------
print("\n[TEST 10] Testing Sensitive Data Masking in Traces...")
try:
    from evals.runner import mask_sensitive
except ImportError:
    from app.evals.runner import mask_sensitive
sample_data = {
    "auth_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.dummy_token_payload",
    "password_hash": "secret_hash_123",
    "otp_code": "123456",
    "bank_account": "112233445566",
    "applicant_name": "Test Citizen"
}
masked = mask_sensitive(sample_data)
check("Token is masked", masked["auth_token"] == "[TOKEN_PROTECTED]")
check("Password / secret is masked", masked["password_hash"] == "***")
check("OTP is masked", masked["otp_code"] == "***")
check("Bank account is masked with last 4 visible", masked["bank_account"] == "XXXXXXXX5566")
check("Safe field unchanged", masked["applicant_name"] == "Test Citizen")

print("\n" + "=" * 75)
print(f"SECURITY & EDGE-CASE TEST SUMMARY: {test_passed} / {test_total} PASSED ({(test_passed/test_total)*100:.1f}%)")
print("=" * 75)
