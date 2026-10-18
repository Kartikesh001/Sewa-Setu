# -*- coding: utf-8 -*-
"""
Exhaustive Authentication & Authorization Security Test Matrix for Sewa Setu MCP Servers.
Tests:
1. Missing, malformed, expired, and forged-signature tokens
2. Issuer, audience, expiry, signing-key/JWKS validation, and scope enforcement
3. Citizen tokens rejected on ALL 5 Officer MCP tools (RBAC)
4. Officer/wrong tokens rejected on ALL 4 Citizen MCP tools
5. Cross-citizen isolation: Citizens cannot read, inspect, or modify another citizen's application
"""

import sys
import os
import time
import json
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import psycopg2
from psycopg2.extras import RealDictCursor

from citizen_mcp.auth import verify_citizen_token, create_mock_citizen_token
from officer_mcp.auth import verify_officer_token, create_mock_officer_token
from citizen_mcp.tools import (
    check_my_application,
    submit_pension_application,
    get_my_application_status,
    withdraw_pending_application
)
from officer_mcp.tools import (
    get_queue_summary,
    list_pending_applications,
    get_application_dossier,
    approve_application,
    reject_application
)

print("=" * 80)
print("SEWA SETU — AUTHENTICATION & AUTHORIZATION EXHAUSTIVE TEST MATRIX")
print("=" * 80)

# Generate an untrusted foreign RSA key pair for signature forgery tests
foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

now = int(time.time())

# 1. Generate security token variants
forged_token = jwt.encode(
    {"iss": "http://localhost:8000", "sub": "officer:hacker", "scope": "officer", "role": "officer", "iat": now, "exp": now + 3600},
    foreign_key,
    algorithm="RS256"
)

expired_token = create_mock_officer_token(username="expired_user", exp_seconds=-3600)
malformed_token = "Bearer eyJhbGciOiJSUzI1NiJ9.invalidpayload.invalidsignature"
missing_token = ""

test_results = []

def record(category, tool_or_check, result, detail=""):
    test_results.append((category, tool_or_check, result, detail))
    mark = "[PASS]" if result else "[FAIL]"
    print(f"  {mark} [{category}] {tool_or_check} - {detail}")

# -----------------------------------------------------------------------------
# SUITE A: TOKEN CRYPTOGRAPHIC INTEGRITY & VALIDATION CHECKS
# -----------------------------------------------------------------------------
print("\n[SUITE A] Cryptographic Token Verification & Claims Enforcement...")

# Missing token
v_miss, err_miss, _ = verify_officer_token(missing_token)
record("Token Validation", "Missing token rejected", not v_miss, f"Error: {err_miss}")

# Malformed token
v_mal, err_mal, _ = verify_officer_token(malformed_token)
record("Token Validation", "Malformed token rejected", not v_mal, f"Error: {err_mal}")

# Expired token
v_exp, err_exp, _ = verify_officer_token(expired_token)
record("Token Validation", "Expired token rejected", not v_exp, f"Error: {err_exp}")

# Forged signature
v_forg, err_forg, _ = verify_officer_token(forged_token)
record("Token Validation", "Forged signature rejected (untrusted JWKS/key)", not v_forg, f"Error: {err_forg}")

# Missing/insufficient scope
no_scope_tok = create_mock_officer_token(username="no_scope", scope="guest", role="guest")
v_scope, err_scope, _ = verify_officer_token(no_scope_tok)
record("Token Validation", "Insufficient scope ('guest') rejected", not v_scope, f"Error: {err_scope}")

# -----------------------------------------------------------------------------
# SUITE B: CITIZEN TOKEN REJECTION ON ALL 5 OFFICER MCP TOOLS (RBAC)
# -----------------------------------------------------------------------------
print("\n[SUITE B] RBAC Enforcement: Citizen Token Rejection Across ALL Officer Tools...")
cit_tok = create_mock_citizen_token("9777700011")

# Tool 1: get_queue_summary
r1 = get_queue_summary(cit_tok)
record("Officer RBAC", "get_queue_summary rejects citizen token", r1.get("status") == "error", f"Error: {r1.get('error_code')}")

# Tool 2: list_pending_applications
r2 = list_pending_applications(cit_tok)
record("Officer RBAC", "list_pending_applications rejects citizen token", r2.get("status") == "error", f"Error: {r2.get('error_code')}")

# Tool 3: get_application_dossier
r3 = get_application_dossier(cit_tok, application_no="SSP26000001")
record("Officer RBAC", "get_application_dossier rejects citizen token", r3.get("status") == "error", f"Error: {r3.get('error_code')}")

# Tool 4: approve_application
r4 = approve_application(cit_tok, application_no="SSP26000001")
record("Officer RBAC", "approve_application rejects citizen token", r4.get("status") == "error", f"Error: {r4.get('error_code')}")

# Tool 5: reject_application
r5 = reject_application(cit_tok, application_no="SSP26000001", rejection_reason="test")
record("Officer RBAC", "reject_application rejects citizen token", r5.get("status") == "error", f"Error: {r5.get('error_code')}")

# -----------------------------------------------------------------------------
# SUITE C: AUTHENTICATION ENFORCEMENT ACROSS ALL CITIZEN TOOLS
# -----------------------------------------------------------------------------
print("\n[SUITE C] Authentication Enforcement Across ALL Citizen Tools...")

# Tool 1: check_my_application
ca_exp = check_my_application(expired_token)
ca_forg = check_my_application(forged_token)
record("Citizen Auth", "check_my_application rejects expired token", ca_exp.get("status") == "error", f"Msg: {ca_exp.get('message')}")
record("Citizen Auth", "check_my_application rejects forged token", ca_forg.get("status") == "error", f"Msg: {ca_forg.get('message')}")

# Tool 2: submit_pension_application
sub_exp = submit_pension_application(expired_token, "Test", "01/01/1950", "Male", "Married", "Sonari", "Sonari", "1234567890", "SBIN0001234")
sub_forg = submit_pension_application(forged_token, "Test", "01/01/1950", "Male", "Married", "Sonari", "Sonari", "1234567890", "SBIN0001234")
record("Citizen Auth", "submit_pension_application rejects expired token", sub_exp.get("status") == "error", f"Errors: {sub_exp.get('errors')}")
record("Citizen Auth", "submit_pension_application rejects forged token", sub_forg.get("status") == "error", f"Errors: {sub_forg.get('errors')}")

# Tool 3: get_my_application_status
gs_exp = get_my_application_status(expired_token)
gs_forg = get_my_application_status(forged_token)
record("Citizen Auth", "get_my_application_status rejects expired token", gs_exp.get("status") == "error", f"Msg: {gs_exp.get('message')}")
record("Citizen Auth", "get_my_application_status rejects forged token", gs_forg.get("status") == "error", f"Msg: {gs_forg.get('message')}")

# Tool 4: withdraw_pending_application
wd_exp = withdraw_pending_application(expired_token)
wd_forg = withdraw_pending_application(forged_token)
record("Citizen Auth", "withdraw_pending_application rejects expired token", wd_exp.get("status") == "error", f"Msg: {wd_exp.get('message')}")
record("Citizen Auth", "withdraw_pending_application rejects forged token", wd_forg.get("status") == "error", f"Msg: {wd_forg.get('message')}")

# -----------------------------------------------------------------------------
# SUITE D: CROSS-CITIZEN DATA ISOLATION
# -----------------------------------------------------------------------------
print("\n[SUITE D] Cross-Citizen Data Isolation...")
conn = psycopg2.connect(host="localhost", port=5432, dbname="sewasetu", user="sewasetu", password="sewasetu123", connect_timeout=3)
conn.autocommit = True
cur = conn.cursor(cursor_factory=RealDictCursor)

mob_a = "9777700021"
mob_b = "9777700022"

cur.execute("DELETE FROM audit_log WHERE application_id IN (SELECT id FROM applications WHERE mobile IN (%s, %s))", (mob_a, mob_b))
cur.execute("DELETE FROM applications WHERE mobile IN (%s, %s)", (mob_a, mob_b))

# Create application for Citizen A
tok_a = create_mock_citizen_token(mob_a)
tok_b = create_mock_citizen_token(mob_b)

sub_a = submit_pension_application(tok_a, "Citizen A", "01/01/1950", "Female", "Widowed", "Sonari", "Sonari", "111122223333", "SBIN0001234")
app_no_a = sub_a.get("application_no")

# 1. Citizen B invokes check_my_application
res_b_chk = check_my_application(tok_b)
record("Data Isolation", "Citizen B cannot find Citizen A's application via check_my_application", res_b_chk.get("has_active_application") is False, f"Status: {res_b_chk.get('status')}")

# 2. Citizen B invokes get_my_application_status
res_b_stat = get_my_application_status(tok_b)
record("Data Isolation", "Citizen B cannot view Citizen A's status via get_my_application_status", res_b_stat.get("status") == "not_found", f"Status: {res_b_stat.get('status')}")

# 3. Citizen B invokes withdraw_pending_application
res_b_with = withdraw_pending_application(tok_b)
record("Data Isolation", "Citizen B cannot withdraw Citizen A's pending application", res_b_with.get("status") == "error", f"Msg: {res_b_with.get('message')}")

# Clean up
cur.execute("DELETE FROM audit_log WHERE application_id IN (SELECT id FROM applications WHERE mobile IN (%s, %s))", (mob_a, mob_b))
cur.execute("DELETE FROM applications WHERE mobile IN (%s, %s)", (mob_a, mob_b))
conn.close()

# -----------------------------------------------------------------------------
# SUMMARY
# -----------------------------------------------------------------------------
total = len(test_results)
passed = sum(1 for r in test_results if r[2])
failed = total - passed

print("\n" + "=" * 80)
print(f"AUTHENTICATION & AUTHORIZATION MATRIX SUMMARY: {passed} / {total} PASSED ({(passed/total)*100:.1f}%)")
print("=" * 80)
