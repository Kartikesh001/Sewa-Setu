"""
Tool implementations for the Block Officer MCP Server.
Provides tools for reviewing the queue, inspecting applicant dossiers,
prioritizing SLA-critical applications, and approving/rejecting cases.
"""

import os
import sys
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List
import requests

try:
    from .config import (
        now_ist, BLOCKS, SLA_DAYS, SMS_GATEWAY_URL, PUBLIC_BASE_URL
    )
    from .db import get_db_cursor
    from .auth import verify_officer_token
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from officer_mcp.config import (
        now_ist, BLOCKS, SLA_DAYS, SMS_GATEWAY_URL, PUBLIC_BASE_URL
    )
    from officer_mcp.db import get_db_cursor
    from officer_mcp.auth import verify_officer_token


def send_officer_sms(mobile: str, text: str) -> bool:
    """Send SMS notification to applicant via the SMS gateway."""
    target_url = SMS_GATEWAY_URL.rstrip("/") + "/api/send"
    try:
        resp = requests.post(target_url, json={"to": mobile, "text": text}, timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass

    # Fallback to standard local smsgw port if gateway URL is internal docker name
    try:
        resp = requests.post("http://localhost:8025/api/send", json={"to": mobile, "text": text}, timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def calculate_age_on(dob: date, on: date) -> int:
    """Calculate age in complete years."""
    if not dob:
        return 0
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def calculate_sla_details(submitted_at: Optional[datetime], decided_at: Optional[datetime] = None) -> Dict[str, Any]:
    """Calculate elapsed days and remaining SLA days for an application."""
    if not submitted_at:
        return {
            "days_elapsed": 0,
            "days_remaining": SLA_DAYS,
            "is_urgent": False,
            "sla_urgency": "NORMAL",
            "sla_deadline": None
        }

    end_time = decided_at or now_ist()
    delta = end_time - submitted_at
    days_elapsed = max(0, round(delta.total_seconds() / 86400.0, 1))
    days_remaining = max(0, round(SLA_DAYS - (delta.total_seconds() / 86400.0), 1))
    sla_deadline = submitted_at + timedelta(days=SLA_DAYS)

    if days_elapsed >= SLA_DAYS:
        urgency = "OVERDUE"
    elif days_remaining <= 3:
        urgency = "URGENT"
    else:
        urgency = "NORMAL"

    return {
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "is_urgent": urgency in ("URGENT", "OVERDUE"),
        "sla_urgency": urgency,
        "sla_deadline": sla_deadline.strftime("%Y-%m-%d %H:%M:%S")
    }


# ---------------------------------------------------------------------------
# Tool 1: Get Queue Summary
# ---------------------------------------------------------------------------

def get_queue_summary(auth_token: str, block: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a high-level summary of the Block Officer review queue.
    Shows pending counts, applications nearing the 15-day SLA (< 3 days remaining),
    and historical decision breakdown.

    Args:
        auth_token: Bearer OAuth 2.1 token with 'officer' scope.
        block: Optional block filter (e.g. 'Sonari', 'Rajapara', etc.).
    """
    is_valid, err, claims = verify_officer_token(auth_token)
    if not is_valid:
        return {"status": "error", "error_code": "AUTH_FAILED", "message": err}

    officer_id = claims.get("officer_id")
    cleaned_block = block.strip() if block else None

    # Verify block if provided
    if cleaned_block:
        matched = next((b for b in BLOCKS if b.lower() == cleaned_block.lower()), None)
        if not matched:
            return {
                "status": "error",
                "error_code": "INVALID_BLOCK",
                "message": f"Block '{block}' is invalid. Allowed blocks: {', '.join(BLOCKS)}"
            }
        cleaned_block = matched

    current_time = now_ist()
    urgent_cutoff = current_time - timedelta(days=(SLA_DAYS - 3))  # 12 days ago
    overdue_cutoff = current_time - timedelta(days=SLA_DAYS)       # 15 days ago
    today_start = datetime(current_time.year, current_time.month, current_time.day)

    try:
        with get_db_cursor() as cur:
            # Base query conditions
            block_sql = " AND block = %s" if cleaned_block else ""
            params_pending = [cleaned_block] if cleaned_block else []

            # 1. Pending counts
            cur.execute(f"SELECT count(*) FROM applications WHERE status = 'PENDING'{block_sql}", params_pending)
            total_pending = cur.fetchone()[0]

            # 2. Urgent pending (submitted >= 12 days ago, i.e. <= 3 days SLA left)
            cur.execute(
                f"SELECT count(*) FROM applications WHERE status = 'PENDING' AND submitted_at <= %s{block_sql}",
                [urgent_cutoff] + params_pending
            )
            urgent_pending = cur.fetchone()[0]

            # 3. Critical overdue (submitted >= 15 days ago, awaiting deemed-approval cron)
            cur.execute(
                f"SELECT count(*) FROM applications WHERE status = 'PENDING' AND submitted_at <= %s{block_sql}",
                [overdue_cutoff] + params_pending
            )
            overdue_pending = cur.fetchone()[0]

            # 4. Decided breakdown
            cur.execute(
                f"""SELECT status, count(*) FROM applications 
                    WHERE status IN ('APPROVED', 'REJECTED', 'DEEMED_APPROVED', 'WITHDRAWN'){block_sql}
                    GROUP BY status""",
                params_pending
            )
            decided_counts = {row[0]: row[1] for row in cur.fetchall()}

            # 5. Decided today
            cur.execute(
                f"""SELECT count(*) FROM applications 
                    WHERE decided_at >= %s{block_sql}""",
                [today_start] + params_pending
            )
            decided_today = cur.fetchone()[0]

            # 6. Block-by-block pending breakdown
            cur.execute(
                """SELECT block, count(*) FROM applications 
                   WHERE status = 'PENDING' 
                   GROUP BY block ORDER BY count(*) DESC"""
            )
            block_breakdown = {row[0]: row[1] for row in cur.fetchall()}

            return {
                "status": "success",
                "officer_id": officer_id,
                "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                "filter_block": cleaned_block or "ALL_BLOCKS",
                "queue": {
                    "total_pending": total_pending,
                    "urgent_pending_approaching_sla": urgent_pending,
                    "normal_pending": max(0, total_pending - urgent_pending),
                    "overdue_pending": overdue_pending,
                    "statutory_sla_days": SLA_DAYS
                },
                "decisions_breakdown": {
                    "approved": decided_counts.get("APPROVED", 0),
                    "rejected": decided_counts.get("REJECTED", 0),
                    "deemed_approved": decided_counts.get("DEEMED_APPROVED", 0),
                    "withdrawn": decided_counts.get("WITHDRAWN", 0),
                    "processed_today": decided_today
                },
                "blocks_summary": block_breakdown,
                "action_guidance": (
                    f"Prioritize the {urgent_pending} application(s) nearing the 15-day SLA."
                    if urgent_pending > 0 else
                    "No applications in immediate SLA breach danger. Process oldest applications first."
                )
            }

    except Exception as e:
        return {"status": "error", "error_code": "DB_ERROR", "message": f"Database query failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Tool 2: List Pending Applications
# ---------------------------------------------------------------------------

def list_pending_applications(
    auth_token: str,
    block: Optional[str] = None,
    sort_by: str = "sla_urgency",
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List pending applications for review.
    Allows filtering by block and prioritizing by SLA urgency (oldest submitted first).

    Args:
        auth_token: Bearer OAuth 2.1 token with 'officer' scope.
        block: Optional block filter ('Sonari', 'Rajapara', 'Dhemaji Pathar', 'Borgaon', 'Namti', 'Khelua').
        sort_by: 'sla_urgency' (default: oldest first), 'oldest', or 'newest'.
        limit: Number of records to return (1 to 100, default 50).
        offset: Number of records to skip for pagination (default 0).
    """
    is_valid, err, claims = verify_officer_token(auth_token)
    if not is_valid:
        return {"status": "error", "error_code": "AUTH_FAILED", "message": err}

    cleaned_block = block.strip() if block else None
    if cleaned_block:
        matched = next((b for b in BLOCKS if b.lower() == cleaned_block.lower()), None)
        if not matched:
            return {
                "status": "error",
                "error_code": "INVALID_BLOCK",
                "message": f"Block '{block}' is invalid. Allowed blocks: {', '.join(BLOCKS)}"
            }
        cleaned_block = matched

    # Enforce limit boundaries
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))

    # Order clause
    sort_lower = (sort_by or "sla_urgency").lower()
    if sort_lower == "newest":
        order_clause = "ORDER BY submitted_at DESC, id DESC"
    else:  # 'sla_urgency' or 'oldest' both prioritize oldest submissions first
        order_clause = "ORDER BY submitted_at ASC, id ASC"

    try:
        with get_db_cursor() as cur:
            block_sql = " AND block = %s" if cleaned_block else ""
            params = [cleaned_block] if cleaned_block else []

            # Total count
            cur.execute(f"SELECT count(*) FROM applications WHERE status = 'PENDING'{block_sql}", params)
            total_count = cur.fetchone()[0]

            # Query list
            query = f"""
                SELECT id, application_no, applicant_name, mobile, dob, village, block, 
                       doc_path, submitted_at 
                FROM applications 
                WHERE status = 'PENDING'{block_sql}
                {order_clause}
                LIMIT %s OFFSET %s
            """
            cur.execute(query, params + [limit, offset])
            rows = cur.fetchall()

            today_date = now_ist().date()
            items = []
            for r in rows:
                app_id, app_no, name, mob, dob, vil, blk, doc_p, sub_at = r
                sla = calculate_sla_details(sub_at)
                age = calculate_age_on(dob, today_date) if dob else None

                items.append({
                    "application_id": app_id,
                    "application_no": app_no,
                    "applicant_name": name,
                    "mobile": mob,
                    "age": age,
                    "village": vil,
                    "block": blk,
                    "document_attached": bool(doc_p and doc_p.strip()),
                    "submitted_at": sub_at.strftime("%Y-%m-%d %H:%M:%S") if sub_at else None,
                    "days_pending": sla["days_elapsed"],
                    "days_remaining_sla": sla["days_remaining"],
                    "sla_urgency": sla["sla_urgency"],
                    "is_sla_critical": sla["is_urgent"]
                })

            return {
                "status": "success",
                "officer_id": claims.get("officer_id"),
                "filter_block": cleaned_block or "ALL_BLOCKS",
                "sort_by": sort_by,
                "pagination": {
                    "total_pending": total_count,
                    "limit": limit,
                    "offset": offset,
                    "returned_count": len(items),
                    "has_more": (offset + len(items)) < total_count
                },
                "applications": items
            }

    except Exception as e:
        return {"status": "error", "error_code": "DB_ERROR", "message": f"Database query failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Tool 3: Get Application Dossier
# ---------------------------------------------------------------------------

def get_application_dossier(
    auth_token: str,
    application_id: Optional[int] = None,
    application_no: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieve the complete dossier of an application for officer verification.
    Includes full applicant personal data, bank details, document path, SLA status,
    and the chronological audit trail.

    Args:
        auth_token: Bearer OAuth 2.1 token with 'officer' scope.
        application_id: Database integer ID of the application.
        application_no: Or official application number (e.g. 'SSP26123456').
    """
    is_valid, err, claims = verify_officer_token(auth_token)
    if not is_valid:
        return {"status": "error", "error_code": "AUTH_FAILED", "message": err}

    if not application_id and not application_no:
        return {
            "status": "error",
            "error_code": "MISSING_IDENTIFIER",
            "message": "Either application_id or application_no must be provided."
        }

    try:
        with get_db_cursor() as cur:
            if application_id:
                cur.execute(
                    """SELECT id, application_no, applicant_name, mobile, dob, gender,
                              marital_status, husband_name, village, block, bank_account,
                              ifsc, doc_path, status, submitted_at, decided_at, decided_by
                       FROM applications WHERE id = %s""",
                    (int(application_id),)
                )
            else:
                cur.execute(
                    """SELECT id, application_no, applicant_name, mobile, dob, gender,
                              marital_status, husband_name, village, block, bank_account,
                              ifsc, doc_path, status, submitted_at, decided_at, decided_by
                       FROM applications WHERE application_no = %s""",
                    (str(application_no).strip(),)
                )

            row = cur.fetchone()
            if not row:
                identifier = application_id or application_no
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": f"Application '{identifier}' not found in the portal records."
                }

            (
                app_id, app_no, name, mob, dob, gender, marital, husband,
                village, block, bank_acc, ifsc, doc_path, status,
                submitted_at, decided_at, decided_by
            ) = row

            # Calculate age and SLA details
            today_date = now_ist().date()
            age = calculate_age_on(dob, today_date) if dob else None
            sla = calculate_sla_details(submitted_at, decided_at)

            # Check document file presence
            doc_exists = bool(doc_path and os.path.exists(doc_path))

            # Fetch chronological audit log
            cur.execute(
                """SELECT id, action, actor, note, at 
                   FROM audit_log 
                   WHERE application_id = %s 
                   ORDER BY at ASC, id ASC""",
                (app_id,)
            )
            audit_rows = cur.fetchall()
            audit_trail = [
                {
                    "log_id": a_id,
                    "action": act,
                    "actor": actor,
                    "note": note or "",
                    "timestamp": at.strftime("%Y-%m-%d %H:%M:%S") if at else None
                }
                for a_id, act, actor, note, at in audit_rows
            ]

            return {
                "status": "success",
                "officer_id": claims.get("officer_id"),
                "application": {
                    "application_id": app_id,
                    "application_no": app_no,
                    "status": status,
                    "personal_details": {
                        "applicant_name": name,
                        "mobile": mob,
                        "date_of_birth": dob.strftime("%d/%m/%Y") if dob else None,
                        "calculated_age": age,
                        "is_age_eligible": (age >= 60) if age is not None else False,
                        "gender": gender,
                        "marital_status": marital,
                        "husband_name": husband or None
                    },
                    "residence": {
                        "village": village,
                        "block": block,
                        "is_block_eligible": block in BLOCKS
                    },
                    "bank_details": {
                        "bank_account": bank_acc,
                        "ifsc": ifsc,
                        "masked_account": ("X" * (len(bank_acc) - 4) + bank_acc[-4:]) if bank_acc and len(bank_acc) > 4 else bank_acc
                    },
                    "document": {
                        "doc_path": doc_path,
                        "filename": os.path.basename(doc_path) if doc_path else None,
                        "file_exists_on_disk": doc_exists
                    },
                    "timeline": {
                        "submitted_at": submitted_at.strftime("%Y-%m-%d %H:%M:%S") if submitted_at else None,
                        "decided_at": decided_at.strftime("%Y-%m-%d %H:%M:%S") if decided_at else None,
                        "decided_by": decided_by,
                        "days_elapsed": sla["days_elapsed"],
                        "days_remaining_sla": sla["days_remaining"],
                        "sla_urgency": sla["sla_urgency"],
                        "sla_deadline": sla["sla_deadline"]
                    },
                    "audit_history": audit_trail
                }
            }

    except Exception as e:
        return {"status": "error", "error_code": "DB_ERROR", "message": f"Database query failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Tool 4: Approve Application
# ---------------------------------------------------------------------------

def approve_application(
    auth_token: str,
    application_id: Optional[int] = None,
    application_no: Optional[str] = None,
    officer_note: Optional[str] = ""
) -> Dict[str, Any]:
    """
    Approve a PENDING pension application.
    Updates database safely, stamps decided_at and decided_by with the authenticated
    officer ID, writes an audit log entry, and triggers an SMS approval notification.

    Args:
        auth_token: Bearer OAuth 2.1 token with 'officer' scope.
        application_id: Database integer ID of the application.
        application_no: Or official application number (e.g. 'SSP26123456').
        officer_note: Optional officer review note / comments.
    """
    is_valid, err, claims = verify_officer_token(auth_token)
    if not is_valid:
        return {"status": "error", "error_code": "AUTH_FAILED", "message": err}

    if not application_id and not application_no:
        return {
            "status": "error",
            "error_code": "MISSING_IDENTIFIER",
            "message": "Either application_id or application_no must be provided."
        }

    officer_id = claims.get("officer_id")
    actor = claims.get("actor", f"officer:{officer_id}")
    decision_time = now_ist()
    cleaned_note = (officer_note or "").strip()[:500]

    try:
        with get_db_cursor(commit=True) as cur:
            # 1. Fetch current application state
            if application_id:
                cur.execute(
                    "SELECT id, application_no, applicant_name, mobile, status FROM applications WHERE id = %s",
                    (int(application_id),)
                )
            else:
                cur.execute(
                    "SELECT id, application_no, applicant_name, mobile, status FROM applications WHERE application_no = %s",
                    (str(application_no).strip(),)
                )

            row = cur.fetchone()
            if not row:
                identifier = application_id or application_no
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": f"Application '{identifier}' not found in the portal records."
                }

            app_id, app_no, applicant_name, mobile, current_status = row

            # 2. Strict status check: only PENDING applications can be approved
            if current_status != "PENDING":
                return {
                    "status": "error",
                    "error_code": "INVALID_STATE",
                    "message": f"Cannot approve application {app_no}: current status is '{current_status}'. Only PENDING applications can be decided."
                }

            # 3. Update application atomically
            cur.execute(
                """UPDATE applications 
                   SET status = 'APPROVED', decided_at = %s, decided_by = %s 
                   WHERE id = %s AND status = 'PENDING'
                   RETURNING application_no""",
                (decision_time, actor, app_id)
            )
            updated = cur.fetchone()
            if not updated:
                return {
                    "status": "error",
                    "error_code": "CONCURRENT_MODIFICATION",
                    "message": f"Application {app_no} was already decided by another session."
                }

            # 4. Insert audit log
            cur.execute(
                """INSERT INTO audit_log (application_id, action, actor, note, at) 
                   VALUES (%s, 'APPROVED', %s, %s, %s)""",
                (app_id, actor, cleaned_note, decision_time)
            )

            # 5. Send SMS notification
            sms_text = f"Sewa Setu: Your pension application {app_no} has been APPROVED by the Block Officer."
            if cleaned_note:
                sms_text += f" Note: {cleaned_note}"
            sms_sent = send_officer_sms(mobile, sms_text)

            return {
                "status": "success",
                "message": f"Application {app_no} successfully APPROVED.",
                "application_id": app_id,
                "application_no": app_no,
                "applicant_name": applicant_name,
                "previous_status": "PENDING",
                "new_status": "APPROVED",
                "decided_by": actor,
                "decided_at": decision_time.strftime("%Y-%m-%d %H:%M:%S"),
                "officer_note": cleaned_note or None,
                "audit_recorded": True,
                "sms_notification": {
                    "mobile": mobile,
                    "sent": sms_sent,
                    "text": sms_text
                }
            }

    except Exception as e:
        return {"status": "error", "error_code": "DB_ERROR", "message": f"Database update failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Tool 5: Reject Application
# ---------------------------------------------------------------------------

def reject_application(
    auth_token: str,
    application_id: Optional[int] = None,
    application_no: Optional[str] = None,
    rejection_reason: str = ""
) -> Dict[str, Any]:
    """
    Reject a PENDING pension application.
    Requires a mandatory rejection reason. Updates database safely, stamps decided_at
    and decided_by with the authenticated officer ID, writes an audit log entry,
    and triggers an SMS rejection notification with the reason.

    Args:
        auth_token: Bearer OAuth 2.1 token with 'officer' scope.
        application_id: Database integer ID of the application.
        application_no: Or official application number (e.g. 'SSP26123456').
        rejection_reason: Mandatory plain-language justification for rejection.
    """
    is_valid, err, claims = verify_officer_token(auth_token)
    if not is_valid:
        return {"status": "error", "error_code": "AUTH_FAILED", "message": err}

    if not application_id and not application_no:
        return {
            "status": "error",
            "error_code": "MISSING_IDENTIFIER",
            "message": "Either application_id or application_no must be provided."
        }

    # Mandatory rejection reason check
    cleaned_reason = (rejection_reason or "").strip()
    if not cleaned_reason:
        return {
            "status": "error",
            "error_code": "MISSING_REASON",
            "message": "A mandatory rejection reason must be provided when rejecting an application."
        }

    officer_id = claims.get("officer_id")
    actor = claims.get("actor", f"officer:{officer_id}")
    decision_time = now_ist()

    try:
        with get_db_cursor(commit=True) as cur:
            # 1. Fetch current application state
            if application_id:
                cur.execute(
                    "SELECT id, application_no, applicant_name, mobile, status FROM applications WHERE id = %s",
                    (int(application_id),)
                )
            else:
                cur.execute(
                    "SELECT id, application_no, applicant_name, mobile, status FROM applications WHERE application_no = %s",
                    (str(application_no).strip(),)
                )

            row = cur.fetchone()
            if not row:
                identifier = application_id or application_no
                return {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": f"Application '{identifier}' not found in the portal records."
                }

            app_id, app_no, applicant_name, mobile, current_status = row

            # 2. Strict status check: only PENDING applications can be rejected
            if current_status != "PENDING":
                return {
                    "status": "error",
                    "error_code": "INVALID_STATE",
                    "message": f"Cannot reject application {app_no}: current status is '{current_status}'. Only PENDING applications can be decided."
                }

            # 3. Update application atomically
            cur.execute(
                """UPDATE applications 
                   SET status = 'REJECTED', decided_at = %s, decided_by = %s 
                   WHERE id = %s AND status = 'PENDING'
                   RETURNING application_no""",
                (decision_time, actor, app_id)
            )
            updated = cur.fetchone()
            if not updated:
                return {
                    "status": "error",
                    "error_code": "CONCURRENT_MODIFICATION",
                    "message": f"Application {app_no} was already decided by another session."
                }

            # 4. Insert audit log with mandatory reason
            cur.execute(
                """INSERT INTO audit_log (application_id, action, actor, note, at) 
                   VALUES (%s, 'REJECTED', %s, %s, %s)""",
                (app_id, actor, cleaned_reason[:500], decision_time)
            )

            # 5. Send SMS notification
            sms_text = f"Sewa Setu: Your pension application {app_no} has been REJECTED. Reason: {cleaned_reason}"
            sms_sent = send_officer_sms(mobile, sms_text)

            return {
                "status": "success",
                "message": f"Application {app_no} successfully REJECTED.",
                "application_id": app_id,
                "application_no": app_no,
                "applicant_name": applicant_name,
                "previous_status": "PENDING",
                "new_status": "REJECTED",
                "decided_by": actor,
                "decided_at": decision_time.strftime("%Y-%m-%d %H:%M:%S"),
                "rejection_reason": cleaned_reason,
                "audit_recorded": True,
                "sms_notification": {
                    "mobile": mobile,
                    "sent": sms_sent,
                    "text": sms_text
                }
            }

    except Exception as e:
        return {"status": "error", "error_code": "DB_ERROR", "message": f"Database update failed: {str(e)}"}
