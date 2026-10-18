#!/usr/bin/env bash
# ==============================================================================
# Sewa Setu - Production Database Restore Script
# Restores a compressed SQL dump to the production PostgreSQL container.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <path_to_backup_file.sql.gz>"
    echo "Example: $0 ./backups/sewasetu_20261018_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "[ERROR] Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# Source environment variables if .env exists
if [ -f "${PROJECT_ROOT}/.env" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
fi

DB_USER="${DB_USER:-sewasetu}"
DB_NAME="${DB_NAME:-sewasetu}"

echo "=============================================================================="
echo "WARNING: RESTORING WILL OVERWRITE EXISTING DATA IN DATABASE '${DB_NAME}'!"
echo "Target backup file: ${BACKUP_FILE}"
echo "=============================================================================="
read -r -p "Are you sure you want to proceed with restore? (yes/no): " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
    echo "[ABORTED] Database restore cancelled by user."
    exit 0
fi

echo "[INFO] Terminating active connections to '${DB_NAME}'..."
docker compose -f "${PROJECT_ROOT}/docker-compose.prod.yml" exec -T db \
    psql -U "${DB_USER}" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null || true

echo "[INFO] Restoring database from: ${BACKUP_FILE}..."
gunzip -c "${BACKUP_FILE}" | docker compose -f "${PROJECT_ROOT}/docker-compose.prod.yml" exec -T db \
    psql -U "${DB_USER}" -d "${DB_NAME}"

echo "[INFO] Verifying restore..."
RECORD_COUNT=$(docker compose -f "${PROJECT_ROOT}/docker-compose.prod.yml" exec -T db \
    psql -U "${DB_USER}" -d "${DB_NAME}" -t -c "SELECT count(*) FROM applications;" | tr -d '[:space:]')

echo "[SUCCESS] Restore finished successfully! Total applications in database: ${RECORD_COUNT}"
