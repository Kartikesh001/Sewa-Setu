"""
Configuration for the Block Officer MCP Server.
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
OFFICER_MCP_PORT = int(os.environ.get("OFFICER_MCP_PORT", "8002"))
OFFICER_MCP_HOST = os.environ.get("OFFICER_MCP_HOST", "0.0.0.0")
OFFICER_MCP_AUDIENCE = os.environ.get("OFFICER_MCP_AUDIENCE", f"http://localhost:{OFFICER_MCP_PORT}/mcp/officer")

# SMS Gateway configuration
SMS_GATEWAY_URL = os.environ.get("SMS_GATEWAY_URL") or ini_config.get("app", "sms_gateway_url", fallback="http://localhost:8000/__gateway")

# Scheme SLA & Jurisdiction
SLA_DAYS = int(os.environ.get("SLA_DAYS") or ini_config.get("pension", "sla_days", fallback="15"))
BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]
ACTIVE_STATUSES = ("PENDING", "APPROVED", "DEEMED_APPROVED")
