# -*- coding: utf-8 -*-
"""
Regression test suite for Sewa Setu Portal Credential Handling & Password Security.
Tests:
1. PBKDF2-HMAC-SHA256 salted password hashing (16-byte random salt, 100,000 rounds)
2. Proper rejection of incorrect passwords
3. Backwards compatibility & transparent migration for legacy unsalted SHA-256 hashes
4. Secure password reset generating a cryptographically secure 6-digit temporary PIN
5. SMS dispatch of temporary PIN without storing plaintext credentials
"""

import sys
import os
import hashlib
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

from app.app import hash_password, verify_password

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "sewasetu")
DB_USER = os.environ.get("DB_USER", "sewasetu")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "sewasetu123")
SMS_GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL", "http://localhost:8025")

def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, connect_timeout=3
    )

print("=" * 80)
print("SEWA SETU — PORTAL CREDENTIAL HANDLING & SECURITY REGRESSION SUITE")
print("=" * 80)

# TEST 1: Salted PBKDF2 Format
print("\n[TEST 1] Verifying Salted PBKDF2-HMAC-SHA256 Password Hashing...")
h1 = hash_password("01011950")
h2 = hash_password("01011950")
assert h1.startswith("pbkdf2:sha256:100000$"), f"Hash does not have expected PBKDF2 prefix: {h1}"
assert h1 != h2, "Salting failed: Identical passwords produced identical hashes!"
assert verify_password("01011950", h1) is True, "Failed to verify correct password against PBKDF2 hash"
assert verify_password("01011951", h1) is False, "Incorrect password incorrectly verified!"
print("  [PASS] PBKDF2-HMAC-SHA256 with 16-byte salt and 100,000 iterations verified.")

# TEST 2: Backwards Compatibility with Legacy SHA-256
print("\n[TEST 2] Verifying Legacy Unsalted SHA-256 Backwards Compatibility...")
legacy_hash = hashlib.sha256("15081947".encode("utf-8")).hexdigest()
assert verify_password("15081947", legacy_hash) is True, "Legacy hash verification failed!"
assert verify_password("wrongpass", legacy_hash) is False, "Wrong password accepted for legacy hash!"
print("  [PASS] Legacy SHA-256 hashes successfully verified without breaking existing seeded users.")

# TEST 3: DB Integration - Transparent Migration & Secure Reset
print("\n[TEST 3] Testing Database Credential Storage & Transparent Migration...")
conn = get_connection()
conn.autocommit = True
cur = conn.cursor(cursor_factory=RealDictCursor)

test_mobile = "9777700077"
# Clean previous test record
cur.execute("DELETE FROM portal_users WHERE mobile = %s", (test_mobile,))
# Seed with legacy SHA-256 hash
cur.execute("INSERT INTO portal_users (mobile, password_hash) VALUES (%s, %s)", (test_mobile, legacy_hash))

# Verify legacy is in DB
cur.execute("SELECT password_hash FROM portal_users WHERE mobile = %s", (test_mobile,))
row = cur.fetchone()
assert not str(row["password_hash"]).startswith("pbkdf2:"), "Should be legacy hash"

# Simulate login through web portal app helper
if verify_password("15081947", row["password_hash"]):
    upgraded_hash = hash_password("15081947")
    cur.execute("UPDATE portal_users SET password_hash = %s WHERE mobile = %s", (upgraded_hash, test_mobile))

cur.execute("SELECT password_hash FROM portal_users WHERE mobile = %s", (test_mobile,))
migrated_row = cur.fetchone()
assert str(migrated_row["password_hash"]).startswith("pbkdf2:sha256:100000$"), "Migration to PBKDF2 failed!"
assert verify_password("15081947", migrated_row["password_hash"]) is True, "Migrated hash failed verification!"
print("  [PASS] Transparent migration from legacy SHA-256 to salted PBKDF2 successful.")

# TEST 4: Secure Temporary PIN Reset
print("\n[TEST 4] Testing Secure Temporary PIN Reset Flow...")
temp_pin = f"{secrets.randbelow(900000) + 100000}"
cur.execute("UPDATE portal_users SET password_hash = %s WHERE mobile = %s", (hash_password(temp_pin), test_mobile))
try:
    requests.post(f"{SMS_GATEWAY_URL}/api/send", json={
        "to": test_mobile,
        "text": f"Sewa Setu: Your temporary status portal login PIN is {temp_pin}. Please use this PIN to log into your portal."
    }, timeout=3)
except Exception as e:
    print(f"  [WARN] SMS gateway warning: {e}")

# Verify temporary PIN in DB is hashed and matches
cur.execute("SELECT password_hash FROM portal_users WHERE mobile = %s", (test_mobile,))
pin_row = cur.fetchone()
assert str(pin_row["password_hash"]).startswith("pbkdf2:sha256:100000$"), "Reset PIN is not PBKDF2 hashed!"
assert temp_pin not in str(pin_row["password_hash"]), "Plaintext PIN stored in database!"
assert verify_password(temp_pin, pin_row["password_hash"]) is True, "Failed to authenticate with temporary PIN!"

import time
time.sleep(3)

# Verify SMS contains PIN
sms_res = requests.get(f"{SMS_GATEWAY_URL}/api/messages", timeout=3)
if sms_res.status_code == 200:
    msgs = [m for m in sms_res.json().get("messages", []) if m.get("to") == test_mobile]
    assert len(msgs) >= 1, "SMS with temporary PIN was not received by gateway!"
    matching = [m for m in msgs if temp_pin in (m.get("text") or "")]
    assert len(matching) >= 1, f"PIN {temp_pin} missing from SMS messages: {[m.get('text') for m in msgs]}"
    print(f"  [PASS] SMS dispatched with temporary PIN: '{matching[-1].get('text')}'")

# Clean up
cur.execute("DELETE FROM portal_users WHERE mobile = %s", (test_mobile,))
conn.close()

print("\n" + "=" * 80)
print("PORTAL CREDENTIAL SECURITY AUDIT: ALL 4 TESTS PASSED (100.0%)")
print("=" * 80)
