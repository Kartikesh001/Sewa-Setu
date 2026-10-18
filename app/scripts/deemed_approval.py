# -*- coding: utf-8 -*-
"""
Nightly deemed-approval job.

Under the Purvanchal Right to Public Services Act, an application not processed
within the statutory SLA stands approved. This job marks such applications
DEEMED_APPROVED and notifies the applicant by SMS.

Scheduled via cron, 02:00 daily. See deploy/crontab.
"""

import os
import sys
import configparser
from datetime import datetime, timedelta

import psycopg2
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

config = configparser.ConfigParser()
CONFIG_PATH = os.path.join(BASE_DIR, "config", "app.ini")
with open(CONFIG_PATH) as fh:
    config.read_file(fh)

SLA_DAYS = config.getint("pension", "sla_days")
SMS_GATEWAY_URL = config.get("app", "sms_gateway_url")


def main():
    db_host = os.environ.get("DB_HOST") or config.get("database", "host", fallback="localhost")
    db_port = int(os.environ.get("DB_PORT") or config.get("database", "port", fallback="5432"))
    db_name = os.environ.get("DB_NAME") or config.get("database", "name", fallback="sewasetu")
    db_user = os.environ.get("DB_USER") or config.get("database", "user", fallback="sewasetu")
    db_pass = os.environ.get("DB_PASSWORD") or config.get("database", "password", fallback="sewasetu123")

    hosts_to_try = [db_host]
    for h in ["db", "localhost"]:
        if h not in hosts_to_try:
            hosts_to_try.append(h)

    conn = None
    for h in hosts_to_try:
        try:
            conn = psycopg2.connect(
                host=h,
                port=db_port,
                dbname=db_name,
                user=db_user,
                password=db_pass,
                connect_timeout=3
            )
            break
        except Exception:
            continue

    if not conn:
        print(f"Error: Could not connect to database on hosts: {hosts_to_try}")
        return 1

    cur = conn.cursor()

    # Atomically update overdue pending applications using database transaction timestamp
    cur.execute(
        """UPDATE applications
           SET status = 'DEEMED_APPROVED', decided_at = NOW(), decided_by = 'RTPS-AUTO'
           WHERE status = 'PENDING' AND submitted_at < NOW() - (%s * INTERVAL '1 day')
           RETURNING id, application_no, mobile, decided_at""",
        (SLA_DAYS,))
    rows = cur.fetchall()

    # Atomically record audit log entries only for the records updated in this execution
    for app_id, app_no, mobile, decided_at in rows:
        cur.execute(
            """INSERT INTO audit_log (application_id, action, actor, note, at)
               VALUES (%s, 'DEEMED_APPROVED', 'RTPS-AUTO', 'not processed within SLA', %s)""",
            (app_id, decided_at)
        )
    conn.commit()

    # Dispatch SMS notifications
    custom_sms = os.environ.get("SMS_GATEWAY_URL")
    if custom_sms:
        sms_urls = [custom_sms]
    else:
        sms_urls = [SMS_GATEWAY_URL, "http://smsgw:8025", "http://localhost:8025"]
    sms_sent_count = 0
    sms_failed_count = 0

    for app_id, app_no, mobile, decided_at in rows:
        sms_sent = False
        last_error = None
        for url in sms_urls:
            if not url:
                continue
            try:
                resp = requests.post(
                    url.rstrip("/") + "/api/send",
                    json={
                        "to": mobile,
                        "text": f"Sewa Setu: your pension application {app_no} stands approved under the RTPS Act."
                    },
                    timeout=5
                )
                if resp.status_code in (200, 201):
                    sms_sent = True
                    break
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:100]}"
            except Exception as e:
                last_error = str(e)
                continue

        if sms_sent:
            sms_sent_count += 1
        else:
            sms_failed_count += 1
            print(f"[SMS WARNING] Failed to deliver deemed-approval SMS for {app_no} to {mobile}: {last_error}", file=sys.stderr)

    print("%s deemed approval: %d applications approved, %d SMS sent, %d SMS failed"
          % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(rows), sms_sent_count, sms_failed_count))
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
