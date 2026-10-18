# -*- coding: utf-8 -*-
"""
Database operations for the Sewa Setu Evaluation Engine.
Stores evaluation runs, scenario execution traces, and before/after verification states.
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import configparser

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_INI = os.path.join(BASE_DIR, "config", "app.ini")

ini_config = configparser.ConfigParser()
if os.path.exists(APP_INI):
    ini_config.read(APP_INI)

DB_HOST = os.environ.get("DB_HOST") or ini_config.get("database", "host", fallback="localhost")
DB_PORT = int(os.environ.get("DB_PORT") or ini_config.get("database", "port", fallback="5432"))
DB_NAME = os.environ.get("DB_NAME") or ini_config.get("database", "name", fallback="sewasetu")
DB_USER = os.environ.get("DB_USER") or ini_config.get("database", "user", fallback="sewasetu")
DB_PASSWORD = os.environ.get("DB_PASSWORD") or ini_config.get("database", "password", fallback="sewasetu123")


def get_db():
    hosts_to_try = [DB_HOST]
    for h in ["db", "localhost"]:
        if h not in hosts_to_try:
            hosts_to_try.append(h)

    last_err = None
    for h in hosts_to_try:
        try:
            return psycopg2.connect(
                host=h,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=3
            )
        except Exception as e:
            last_err = e
    raise ConnectionError(f"Could not connect to PostgreSQL: {last_err}")


def init_eval_tables():
    """Ensure evaluation schema tables exist."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) UNIQUE,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                status VARCHAR(20) DEFAULT 'RUNNING',
                total_scenarios INTEGER DEFAULT 6,
                passed_scenarios INTEGER DEFAULT 0,
                failed_scenarios INTEGER DEFAULT 0,
                sla_compliance_rate NUMERIC(5,2) DEFAULT 0.0,
                avg_turns NUMERIC(4,1) DEFAULT 0.0,
                duration_ms INTEGER DEFAULT 0,
                summary JSONB DEFAULT '{}'::jsonb
            );

            CREATE TABLE IF NOT EXISTS eval_results (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64),
                scenario_id VARCHAR(50),
                persona_name VARCHAR(100),
                persona_role VARCHAR(20),
                persona_age INTEGER,
                persona_block VARCHAR(50),
                scenario_title VARCHAR(200),
                challenge_description TEXT,
                expected_outcome TEXT,
                actual_outcome TEXT,
                status VARCHAR(20),
                turns_count INTEGER DEFAULT 0,
                conversation_trace JSONB DEFAULT '[]'::jsonb,
                db_before JSONB DEFAULT '{}'::jsonb,
                db_after JSONB DEFAULT '{}'::jsonb,
                audit_entries JSONB DEFAULT '[]'::jsonb,
                sms_messages JSONB DEFAULT '[]'::jsonb,
                assertions JSONB DEFAULT '[]'::jsonb,
                error_message TEXT,
                duration_ms INTEGER DEFAULT 0,
                created_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_eval_runs_started ON eval_runs(started_at DESC);
            """)
            conn.commit()
    finally:
        conn.close()


def create_eval_run(run_id):
    init_eval_tables()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO eval_runs (run_id, started_at, status)
                VALUES (%s, %s, 'RUNNING')
            """, (run_id, datetime.now()))
            conn.commit()
    finally:
        conn.close()


def update_eval_run(run_id, status, passed, failed, sla_rate, avg_turns, duration_ms, summary=None):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE eval_runs
                SET status = %s,
                    completed_at = %s,
                    passed_scenarios = %s,
                    failed_scenarios = %s,
                    sla_compliance_rate = %s,
                    avg_turns = %s,
                    duration_ms = %s,
                    summary = %s
                WHERE run_id = %s
            """, (
                status,
                datetime.now(),
                passed,
                failed,
                sla_rate,
                avg_turns,
                duration_ms,
                json.dumps(summary or {}),
                run_id
            ))
            conn.commit()
    finally:
        conn.close()


def save_eval_result(res):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO eval_results (
                    run_id, scenario_id, persona_name, persona_role, persona_age, persona_block,
                    scenario_title, challenge_description, expected_outcome, actual_outcome,
                    status, turns_count, conversation_trace, db_before, db_after,
                    audit_entries, sms_messages, assertions, error_message, duration_ms, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
            """, (
                res["run_id"],
                res["scenario_id"],
                res["persona_name"],
                res["persona_role"],
                res.get("persona_age", 0),
                res.get("persona_block", ""),
                res["scenario_title"],
                res["challenge_description"],
                res["expected_outcome"],
                res.get("actual_outcome", ""),
                res["status"],
                res.get("turns_count", 0),
                json.dumps(res.get("conversation_trace", [])),
                json.dumps(res.get("db_before", {})),
                json.dumps(res.get("db_after", {})),
                json.dumps(res.get("audit_entries", [])),
                json.dumps(res.get("sms_messages", [])),
                json.dumps(res.get("assertions", [])),
                res.get("error_message"),
                res.get("duration_ms", 0),
                datetime.now()
            ))
            conn.commit()
    finally:
        conn.close()


def get_latest_eval_run():
    init_eval_tables()
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM eval_runs
                ORDER BY started_at DESC
                LIMIT 1
            """)
            run = cur.fetchone()
            if not run:
                return None

            cur.execute("""
                SELECT * FROM eval_results
                WHERE run_id = %s
                ORDER BY id ASC
            """, (run["run_id"],))
            results = cur.fetchall()
            run["results"] = results
            return dict(run)
    finally:
        conn.close()


def get_eval_run(run_id):
    init_eval_tables()
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM eval_runs WHERE run_id = %s", (run_id,))
            run = cur.fetchone()
            if not run:
                return None
            cur.execute("SELECT * FROM eval_results WHERE run_id = %s ORDER BY id ASC", (run_id,))
            run["results"] = cur.fetchall()
            return dict(run)
    finally:
        conn.close()


def get_all_eval_runs(limit=10):
    init_eval_tables()
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, run_id, started_at, completed_at, status, total_scenarios,
                       passed_scenarios, failed_scenarios, sla_compliance_rate, avg_turns, duration_ms
                FROM eval_runs
                ORDER BY started_at DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()
    finally:
        conn.close()
