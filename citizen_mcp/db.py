"""
Database connection and query helpers for the Citizen MCP Server.
"""

import os
import sys
import psycopg2
from contextlib import contextmanager

try:
    from .config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from citizen_mcp.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


def get_db_connection():
    """Create a new PostgreSQL connection."""
    hosts_to_try = [DB_HOST]
    for fallback in ["db", "localhost"]:
        if fallback not in hosts_to_try:
            hosts_to_try.append(fallback)

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

    raise ConnectionError(f"Could not connect to PostgreSQL database: {last_err}")


@contextmanager
def get_db_cursor(commit=False):
    """Context manager yielding a cursor, automatically handling commit/rollback and closing."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
