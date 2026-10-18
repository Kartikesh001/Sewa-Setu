"""
Tool implementations for the Citizen MCP Server.
Implements the exact scheme rules, validations, and operations
defined by the Department of Social Welfare.
"""

import re
import random
import hashlib
from datetime import datetime, date
from typing import Dict, Any, Optional

import requests
import os
import sys

try:
    from .config import (
        now_ist, BLOCKS, MIN_AGE, SLA_DAYS, SCHEME_DEADLINE,
        ACTIVE_STATUSES, SMS_GATEWAY_URL, PUBLIC_BASE_URL
    )
    from .db import get_db_cursor
    from .auth import verify_citizen_token
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from citizen_mcp.config import (
        now_ist, BLOCKS, MIN_AGE, SLA_DAYS, SCHEME_DEADLINE,
        ACTIVE_STATUSES, SMS_GATEWAY_URL, PUBLIC_BASE_URL
    )
    from citizen_mcp.db import get_db_cursor
    from citizen_mcp.auth import verify_citizen_token


def sanitize(val: Optional[str], maxlen: int = 100) -> str:
    """Trim whitespace and cap length preserving Unicode characters."""
    if not val:
        return ""
    return str(val).strip()[:maxlen]


def parse_dob(raw: Optional[str]) -> Optional[date]:
    """Parse date of birth in DD/MM/YYYY format."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def calculate_age_on(dob: date, on: date) -> int:
    """Calculate age in complete years."""
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def generate_application_no() -> str:
    """Generate official application number format: SSP<YY><6-digits>."""
    return f"SSP{datetime.now().strftime('%y')}{random.randint(100000, 999999)}"


def send_citizen_sms(mobile: str, text: str) -> None:
    """Send SMS notification to applicant via the SMS gateway."""
    target_url = SMS_GATEWAY_URL.rstrip("/") + "/api/send"
    try:
        requests.post(target_url, json={"to": mobile, "text": text}, timeout=3)
    except Exception:
        # Fallback to standard smsgw port if gateway URL is internal docker name
        try:
            requests.post("http://localhost:8025/api/send", json={"to": mobile, "text": text}, timeout=2)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tool 1: Scheme Guidelines
# ---------------------------------------------------------------------------

def get_scheme_guidelines() -> Dict[str, Any]:
    """
    Get official guidelines and rules for the Old Age Pension scheme.
    Use this tool to inform citizens accurately without guessing or hallucinating.
    """
    now = now_ist()
    hours_left = int((SCHEME_DEADLINE - now).total_seconds() // 3600) if SCHEME_DEADLINE > now else 0
    is_open = SCHEME_DEADLINE > now

    return {
        "scheme_name": "Old Age Pension Scheme (Indira Gandhi National Old Age Pension / State Pension)",
        "department": "Department of Social Welfare, Government of Purvanchal",
        "monthly_pension": "₹250 per month",
        "eligibility_criteria": {
            "minimum_age": f"{MIN_AGE} years of age or above",
            "jurisdiction": f"Residents of the following blocks: {', '.join(BLOCKS)}",
            "documentation": "Age proof document (Aadhaar / Voter ID / School certificate / Medical certificate) and valid Bank Account with IFSC"
        },
        "service_level_agreement": f"{SLA_DAYS}-day statutory SLA (Applications pending beyond {SLA_DAYS} days are deemed approved by law)",
        "application_window": {
            "status": "OPEN" if is_open else "CLOSED",
            "deadline": SCHEME_DEADLINE.strftime("%d %B %Y, %I:%M %p"),
            "hours_remaining": hours_left
        },
        "important_rules": [
            "An applicant may hold at most one active application (Pending, Approved, or Deemed Approved) at a time.",
            "If an application has an error, it can be withdrawn while pending, allowing the citizen to re-apply.",
            "Rejected or withdrawn applications do not prevent filing a new application."
        ]
    }


# ---------------------------------------------------------------------------
# Tool 2: Check Eligibility
# ---------------------------------------------------------------------------

def check_eligibility(dob: str, block: str) -> Dict[str, Any]:
    """
    Check if a person is eligible based on Date of Birth and Block.

    Args:
        dob: Date of birth in DD/MM/YYYY format (e.g. '15/08/1954').
        block: Block name (must be one of Sonari, Rajapara, Dhemaji Pathar, Borgaon, Namti, Khelua).
    """
    errors = []
    parsed = parse_dob(dob)
    age = None

    if not parsed:
        errors.append("Date of birth must be provided in DD/MM/YYYY format (e.g. 15/08/1954).")
    else:
        current_date = now_ist().date()
        age = calculate_age_on(parsed, current_date)
        if age < MIN_AGE:
            try:
                eligible_date = parsed.replace(year=parsed.year + MIN_AGE)
                errors.append(f"Applicant is {age} years old. The statutory minimum age is {MIN_AGE} years. Applicant will become eligible on {eligible_date.strftime('%d/%m/%Y')} (Year {eligible_date.year}).")
            except Exception:
                errors.append(f"Applicant is {age} years old. The statutory minimum age is {MIN_AGE} years. Applicant will become eligible in {parsed.year + MIN_AGE}.")

    cleaned_block = (block or "").strip()
    matched_block = next((b for b in BLOCKS if b.lower() == cleaned_block.lower()), None)
    if not matched_block:
        errors.append(f"Block '{block}' is not covered. Eligible blocks are: {', '.join(BLOCKS)}.")

    if now_ist() > SCHEME_DEADLINE:
        errors.append("The scheme application window has closed.")

    is_eligible = len(errors) == 0
    return {
        "eligible": is_eligible,
        "calculated_age": age,
        "verified_block": matched_block,
        "errors": errors,
        "guidance": (
            "Applicant is eligible! You may proceed to collect bank details and submit the application."
            if is_eligible else
            "Applicant is currently not eligible. Please explain the reasons clearly."
        )
    }


# ---------------------------------------------------------------------------
# Tool 3: Check Existing Application
# ---------------------------------------------------------------------------

def check_my_application(auth_token: str) -> Dict[str, Any]:
    """
    Check whether the authenticated citizen already holds an application on the portal.

    Args:
        auth_token: The citizen's OAuth 2.1 access token.
    """
    valid, err, claims = verify_citizen_token(auth_token)
    if not valid:
        return {"status": "error", "message": err}

    mobile = claims["mobile"]

    with get_db_cursor() as cur:
        cur.execute(
            """SELECT id, application_no, applicant_name, village, block, status, submitted_at, decided_at, decided_by
               FROM applications
               WHERE mobile = %s
               ORDER BY submitted_at DESC LIMIT 1""",
            (mobile,)
        )
        row = cur.fetchone()

    if not row:
        return {
            "status": "none",
            "mobile": mobile,
            "has_active_application": False,
            "message": "No previous applications found for this mobile number. You may submit a new application."
        }

    app_id, app_no, name, village, block, status, submitted_at, decided_at, decided_by = row
    is_active = status in ACTIVE_STATUSES

    return {
        "status": status,
        "mobile": mobile,
        "application_no": app_no,
        "applicant_name": name,
        "village": village,
        "block": block,
        "has_active_application": is_active,
        "submitted_at": submitted_at.strftime("%d/%m/%Y %H:%M") if submitted_at else None,
        "decided_at": decided_at.strftime("%d/%m/%Y %H:%M") if decided_at else None,
        "message": (
            f"You have an active {status} application ({app_no}). Citizens cannot hold more than one active application."
            if is_active else
            f"Your previous application ({app_no}) is {status}. You are eligible to submit a fresh application."
        )
    }


# ---------------------------------------------------------------------------
# Tool 4: Submit Application
# ---------------------------------------------------------------------------

def submit_pension_application(
    auth_token: str,
    applicant_name: str,
    dob: str,
    gender: str,
    marital_status: str,
    village: str,
    block: str,
    bank_account: str,
    ifsc: str,
    husband_name: str = "",
    doc_path: str = "age_proof_self_attested.pdf"
) -> Dict[str, Any]:
    """
    Submit a validated Old Age Pension application for the authenticated citizen.

    Args:
        auth_token: The citizen's OAuth 2.1 access token.
        applicant_name: Full legal name of the applicant.
        dob: Date of birth as DD/MM/YYYY.
        gender: Gender (e.g. 'Female', 'Male', 'Other').
        marital_status: Marital status (e.g. 'Widow', 'Married', 'Unmarried').
        village: Village or town name.
        block: Block name (must be one of: Sonari, Rajapara, Dhemaji Pathar, Borgaon, Namti, Khelua).
        bank_account: 9 to 18 digit bank account number without spaces or dashes.
        ifsc: 11-character bank IFSC code (e.g. 'SBIN0003077').
        husband_name: Husband's name (if applicant is female/widow).
        doc_path: Age proof document reference or file path.
    """
    valid, err, claims = verify_citizen_token(auth_token)
    if not valid:
        return {"status": "error", "errors": [err]}

    mobile = claims["mobile"]

    # 1. Normalization & Sanitization
    cleaned_name = sanitize(applicant_name)
    cleaned_village = sanitize(village)
    cleaned_block = sanitize(block)
    cleaned_bank = re.sub(r"[\s-]", "", bank_account or "")
    cleaned_ifsc = re.sub(r"[\s-]", "", ifsc or "").upper()
    cleaned_doc = sanitize(doc_path)
    cleaned_gender = sanitize(gender, 10)
    cleaned_marital = sanitize(marital_status, 20)
    cleaned_husband = sanitize(husband_name)

    # 2. Strict Scheme Validation
    errors = []
    if not cleaned_name:
        errors.append("Applicant full name is required.")
    if not cleaned_village:
        errors.append("Village is required.")
    if not cleaned_block:
        errors.append("Block is required.")

    matched_block = next((b for b in BLOCKS if b.lower() == cleaned_block.lower()), None)
    if not matched_block:
        errors.append(f"Block must be one of: {', '.join(BLOCKS)}.")
    else:
        cleaned_block = matched_block

    if not cleaned_bank or not re.fullmatch(r"\d{9,18}", cleaned_bank):
        errors.append("Bank account number must be between 9 and 18 digits.")

    if not cleaned_ifsc or not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", cleaned_ifsc):
        errors.append("IFSC code must be 11 characters (e.g. SBIN0003077).")

    parsed_dob = parse_dob(dob)
    if not parsed_dob:
        errors.append("Date of birth must be given in DD/MM/YYYY format.")
    else:
        age = calculate_age_on(parsed_dob, now_ist().date())
        if age < MIN_AGE:
            errors.append(f"Applicant is {age} years of age; scheme requires {MIN_AGE} years or above.")

    if not cleaned_doc:
        errors.append("Age proof document reference is required.")

    if now_ist() > SCHEME_DEADLINE:
        errors.append("The scheme application window has closed.")

    if errors:
        return {"status": "validation_failed", "errors": errors}

    # 3. Database Insertion & System of Record Update
    with get_db_cursor(commit=True) as cur:
        # Check active applications
        cur.execute(
            "SELECT id, application_no, status FROM applications "
            "WHERE mobile = %s AND status IN %s ORDER BY submitted_at DESC LIMIT 1",
            (mobile, ACTIVE_STATUSES)
        )
        existing = cur.fetchone()
        if existing:
            return {
                "status": "rejected_duplicate",
                "errors": [
                    f"Mobile number {mobile} already holds an active {existing[2]} application ({existing[1]}). "
                    "You cannot file a second application while one is active."
                ]
            }

        app_no = generate_application_no()
        now_ts = now_ist()

        cur.execute(
            """INSERT INTO applications
               (application_no, applicant_name, mobile, dob, gender, marital_status,
                husband_name, husband_employer, village, block, bank_account, ifsc,
                doc_path, status, submitted_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)
               RETURNING id""",
            (app_no, cleaned_name, mobile, parsed_dob, cleaned_gender, cleaned_marital,
             cleaned_husband, "", cleaned_village, cleaned_block, cleaned_bank, cleaned_ifsc,
             cleaned_doc, now_ts)
        )
        app_id = cur.fetchone()[0]

        # Ensure status portal user exists (salted PBKDF2 hash of onboarding credential)
        import secrets
        dob_pw = parsed_dob.strftime("%d%m%Y")
        salt = secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac("sha256", dob_pw.encode("utf-8"), salt, 100000)
        pw_hash = f"pbkdf2:sha256:100000${salt.hex()}${derived.hex()}"
        cur.execute(
            "INSERT INTO portal_users (mobile, password_hash) VALUES (%s, %s) "
            "ON CONFLICT (mobile) DO UPDATE SET password_hash = EXCLUDED.password_hash",
            (mobile, pw_hash)
        )

        # Write audit trail
        cur.execute(
            "INSERT INTO audit_log (application_id, action, actor, note, at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (app_id, "SUBMIT", f"citizen:{mobile}", "Submitted via Citizen AI Assistant (MCP)", datetime.now())
        )

    # 4. Send Confirmation SMS
    sms_text = (
        f"Your Sewa Setu pension application ({app_no}) is received and is pending verification. "
        f"Password for status portal: {parsed_dob.strftime('%d%m%Y')}."
    )
    send_citizen_sms(mobile, sms_text)

    return {
        "status": "success",
        "application_no": app_no,
        "application_id": app_id,
        "applicant_name": cleaned_name,
        "mobile": mobile,
        "block": cleaned_block,
        "current_status": "PENDING",
        "submitted_at": now_ts.strftime("%d/%m/%Y %H:%M"),
        "status_portal_password": parsed_dob.strftime("%d%m%Y"),
        "message": (
            f"Application {app_no} submitted successfully! It is now with the {cleaned_block} Block Officer. "
            f"Under statutory SLA, if not decided within {SLA_DAYS} days it will be deemed approved."
        )
    }


# ---------------------------------------------------------------------------
# Tool 5: Get Application Status
# ---------------------------------------------------------------------------

def get_my_application_status(auth_token: str) -> Dict[str, Any]:
    """
    Get real-time status and SLA tracking for the citizen's application.

    Args:
        auth_token: The citizen's OAuth 2.1 access token.
    """
    valid, err, claims = verify_citizen_token(auth_token)
    if not valid:
        return {"status": "error", "message": err}

    mobile = claims["mobile"]

    with get_db_cursor() as cur:
        cur.execute(
            """SELECT id, application_no, applicant_name, village, block, status,
                      submitted_at, decided_at, decided_by
               FROM applications
               WHERE mobile = %s
               ORDER BY submitted_at DESC LIMIT 1""",
            (mobile,)
        )
        app_row = cur.fetchone()
        if not app_row:
            return {"status": "not_found", "message": "No application found for your mobile number."}

        app_id, app_no, name, village, block, status, submitted_at, decided_at, decided_by = app_row

        cur.execute(
            "SELECT action, actor, note, at FROM audit_log WHERE application_id = %s ORDER BY at ASC",
            (app_id,)
        )
        audit_rows = cur.fetchall()

    days_pending = None
    sla_days_left = None
    if submitted_at:
        days_pending = (now_ist() - submitted_at).days
        if status == "PENDING":
            sla_days_left = max(0, SLA_DAYS - days_pending)

    history = [
        {"action": r[0], "actor": r[1], "note": r[2], "at": r[3].strftime("%d/%m/%Y %H:%M")}
        for r in audit_rows
    ]

    return {
        "status": status,
        "application_no": app_no,
        "applicant_name": name,
        "block": block,
        "village": village,
        "submitted_at": submitted_at.strftime("%d/%m/%Y %H:%M") if submitted_at else None,
        "decided_at": decided_at.strftime("%d/%m/%Y %H:%M") if decided_at else None,
        "decided_by": decided_by,
        "days_since_submission": days_pending,
        "sla_days_remaining": sla_days_left,
        "audit_history": history,
        "summary": (
            f"Application {app_no} is currently {status} with the {block} block office. "
            + (f"Statutory deemed approval in ~{sla_days_left} day(s)." if status == "PENDING" else "")
        )
    }


# ---------------------------------------------------------------------------
# Tool 6: Withdraw Application
# ---------------------------------------------------------------------------

def withdraw_pending_application(auth_token: str, reason: str = "") -> Dict[str, Any]:
    """
    Withdraw an active PENDING application so the applicant can submit a corrected application.

    Args:
        auth_token: The citizen's OAuth 2.1 access token.
        reason: Optional reason for withdrawing (e.g. 'Typo in bank details').
    """
    valid, err, claims = verify_citizen_token(auth_token)
    if not valid:
        return {"status": "error", "message": err}

    mobile = claims["mobile"]

    with get_db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT id, application_no, applicant_name FROM applications "
            "WHERE mobile = %s AND status = 'PENDING' ORDER BY submitted_at DESC LIMIT 1",
            (mobile,)
        )
        row = cur.fetchone()
        if not row:
            return {
                "status": "error",
                "message": "No active PENDING application found to withdraw. Only pending applications can be withdrawn."
            }

        app_id, app_no, name = row
        now_ts = now_ist()

        cur.execute(
            "UPDATE applications SET status = 'WITHDRAWN', decided_at = %s, decided_by = %s WHERE id = %s",
            (now_ts, f"citizen:{mobile}", app_id)
        )

        note_text = sanitize(reason) or "Withdrawn by applicant via Citizen AI Assistant"
        cur.execute(
            "INSERT INTO audit_log (application_id, action, actor, note, at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (app_id, "WITHDRAW", f"citizen:{mobile}", note_text, datetime.now())
        )

    send_citizen_sms(mobile, f"Your Old Age Pension application {app_no} has been withdrawn.")

    return {
        "status": "success",
        "application_no": app_no,
        "applicant_name": name,
        "message": f"Application {app_no} was successfully withdrawn. You are now free to submit a fresh application with correct details."
    }
