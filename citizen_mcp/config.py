"""
Configuration for the Citizen MCP Server.
Reads settings from app/config/app.ini and environment variables
without altering any existing application files.
"""

import os
import configparser
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    """Returns current datetime in Indian Standard Time (naive)."""
    return datetime.now(IST).replace(tzinfo=None)


# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
candidate_paths = [
    os.path.join(PROJECT_ROOT, "app", "config", "app.ini"),
    os.path.join(PROJECT_ROOT, "config", "app.ini"),
]
APP_INI = next((p for p in candidate_paths if os.path.exists(p)), candidate_paths[0])

ini_config = configparser.ConfigParser()
if os.path.exists(APP_INI):
    ini_config.read(APP_INI)


# Database configuration
DB_HOST = os.environ.get("DB_HOST") or (ini_config.get("database", "host", fallback="localhost"))
DB_PORT = int(os.environ.get("DB_PORT") or ini_config.get("database", "port", fallback="5432"))
DB_NAME = os.environ.get("DB_NAME") or ini_config.get("database", "name", fallback="sewasetu")
DB_USER = os.environ.get("DB_USER") or ini_config.get("database", "user", fallback="sewasetu")
DB_PASSWORD = os.environ.get("DB_PASSWORD") or ini_config.get("database", "password", fallback="sewasetu123")

# Portal & Auth configuration
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
CITIZEN_MCP_PORT = int(os.environ.get("CITIZEN_MCP_PORT", "8001"))
CITIZEN_MCP_HOST = os.environ.get("CITIZEN_MCP_HOST", "0.0.0.0")
CITIZEN_MCP_AUDIENCE = os.environ.get("CITIZEN_MCP_AUDIENCE", f"http://localhost:{CITIZEN_MCP_PORT}/mcp")

# SMS Gateway configuration
SMS_GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL") or ini_config.get("app", "sms_gateway_url", fallback="http://localhost:8000/__gateway")

# Pension scheme rules
MIN_AGE = int(os.environ.get("MIN_AGE") or ini_config.get("pension", "min_age", fallback="60"))
SLA_DAYS = int(os.environ.get("SLA_DAYS") or ini_config.get("pension", "sla_days", fallback="15"))
RAW_DEADLINE = os.environ.get("SCHEME_DEADLINE") or ini_config.get("pension", "scheme_deadline", fallback="2026-10-31 23:59")
try:
    SCHEME_DEADLINE = datetime.strptime(RAW_DEADLINE, "%Y-%m-%d %H:%M")
except Exception:
    SCHEME_DEADLINE = datetime(2026, 10, 31, 23, 59)

BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]
ACTIVE_STATUSES = ("PENDING", "APPROVED", "DEEMED_APPROVED")
