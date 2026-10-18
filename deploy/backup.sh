#!/usr/bin/env bash
# ==============================================================================
# Sewa Setu - Production Database Backup Script
# Creates a compressed, timestamped pg_dump of the PostgreSQL database.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_ROOT}/backups"
TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/sewasetu_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Source environment variables if .env exists
if [ -f "${PROJECT_ROOT}/.env" ]; then
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
fi

DB_USER="${DB_USER:-sewasetu}"
DB_NAME="${DB_NAME:-sewasetu}"

echo "[INFO] Starting database backup: ${TIMESTAMP}"

# Run pg_dump inside the container and stream to gzip
docker compose -f "${PROJECT_ROOT}/docker-compose.prod.yml" exec -T db \
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists | gzip > "${BACKUP_FILE}"

# Verify backup size
BACKUP_SIZE="$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || stat -f%z "${BACKUP_FILE}" 2>/dev/null || echo "0")"

if [ "${BACKUP_SIZE}" -gt 100 ]; then
    echo "[SUCCESS] Backup completed: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"
else
    echo "[ERROR] Backup failed or file is empty: ${BACKUP_FILE}"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# Retention policy: Prune backups older than 14 days
find "${BACKUP_DIR}" -name "sewasetu_*.sql.gz" -type f -mtime +14 -delete || true
echo "[INFO] Retention check complete: kept backups from the last 14 days."
