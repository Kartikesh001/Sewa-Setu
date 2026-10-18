# Sewa Setu — Low-Memory Production Deployment Runbook (Ubuntu 26.04 LTS VPS)

This runbook provides the verified, low-resource deployment procedure for the **Sewa Setu Old Age Pension System** on an **InterServer Ubuntu 26.04.1 LTS VPS** (1 vCPU, ~1.6 GiB RAM, 1 GiB swap, 38 GB disk, Docker & Docker Compose pre-installed).

---

## 1. Low-Memory Architecture & Resource Allocation

Given the 1.6 GiB RAM and 1 CPU constraint, services have been specifically tuned to keep the entire Docker stack under **400 MiB total memory footprint**:

| Service | Low-Memory Configuration | Estimated RAM | Role / Scope |
|---|---|---|---|
| **db** (PostgreSQL 15 Alpine) | `shared_buffers=64MB`, `work_mem=4MB`, `max_connections=25` | ~60–80 MiB | Relational datastore (**Internal only**) |
| **app** (Flask Portal & OAuth) | Gunicorn `2 workers`, `2 threads`, `timeout 60` | ~100–120 MiB | Web portal, `/eval-dashboard`, OAuth 2.1 |
| **citizen_mcp** | Uvicorn ASGI single process | ~60–75 MiB | Streamable HTTP MCP for citizens (`/mcp`) |
| **officer_mcp** | Uvicorn ASGI single process | ~60–75 MiB | Streamable HTTP MCP for officers (`/mcp/officer`) |
| **smsgw** (Mock SMS) | Lightweight Python Flask single process | ~25–35 MiB | Internal mock SMS service |
| **proxy** (Nginx 1.25 Alpine) | Stream proxy, micro-caching, SSE buffering disabled | ~10–15 MiB | Reverse proxy, rate limiting, SSL termination |
| **scheduler** | **Disabled (Profile: `manual-scheduler`)** | **0 MiB** | **Does not run**; deemed approval cannot trigger |
| **TOTAL STACK FOOTPRINT** | | **~350–390 MiB** | Leaves **~1.2 GiB RAM** headroom for OS & buffers |

---

## 2. Server Verification & Firewall Hardening

### Step 2.1: Verify Pre-installed Docker & Compose
Since Docker and Docker Compose are already installed on your VPS, verify their versions:
```bash
docker --version
docker compose version
```

### Step 2.2: Configure Firewall (UFW)
Expose only SSH, HTTP, and HTTPS. All internal services (`5432`, `8000`, `8001`, `8002`, `8025`) remain strictly firewalled:
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status verbose
```

---

## 3. Deployment Directory & Secret Generation

### Step 3.1: Prepare Application Directory
```bash
sudo mkdir -p /opt/sewasetu
sudo chown -R $USER:$USER /opt/sewasetu
cd /opt/sewasetu

# Copy or clone the project files into /opt/sewasetu
# (Ensure git tracks only sanitized code; .gitignore prevents secret leaks)
```

### Step 3.2: Configure Production Environment (`.env`)
```bash
cp .env.example .env

# Generate cryptographically secure random secrets
PG_PASS=$(openssl rand -hex 16)
FLASK_SEC=$(openssl rand -hex 32)
ADM_PASS=$(openssl rand -hex 16)

sed -i "s/generate_a_secure_postgres_password_here/$PG_PASS/" .env
sed -i "s/generate_a_cryptographically_secure_flask_secret_key_here/$FLASK_SEC/" .env
sed -i "s/generate_a_strong_unique_admin_password_here/$ADM_PASS/" .env

# Set PUBLIC_BASE_URL (for an initial IP smoke test, use http://<YOUR_VPS_IP>)
nano .env

# Restrict permissions
chmod 600 .env
chmod +x deploy/*.sh
```

---

## 4. Controlled First Launch & Schema Initialization

### Step 4.1: Launch Base Services (Without Scheduler)
```bash
# Build the unified image and launch services in background
docker compose -f docker-compose.prod.yml up -d --build

# Verify container statuses (scheduler will NOT be started)
docker compose -f docker-compose.prod.yml ps
```

### Step 4.2: Explicit Database Schema Initialization
As required by the strict safety rules, no schema migrations or seeds execute automatically.
Run the reviewed schema creation explicitly:
```bash
# Initialize schema tables (clean empty database)
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U sewasetu -d sewasetu < app/schema.sql

# Verify tables were created
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U sewasetu -d sewasetu -c "\dt"
```

---

## 5. Verification & Smoke Testing (IP-Only vs HTTPS)

### What Works with an IP-Only HTTP Smoke Test:
- **Web Portal Navigation**: `http://<VPS_IP>/`, `http://<VPS_IP>/apply`, `http://<VPS_IP>/track`
- **Evaluation Dashboard**: `http://<VPS_IP>/eval-dashboard`
- **Portal Health Check**: `http://<VPS_IP>/health`
- **Citizen MCP Endpoint**: `http://<VPS_IP>/mcp` and `http://<VPS_IP>/mcp/health`
- **Officer MCP Endpoint**: `http://<VPS_IP>/mcp/officer` and `http://<VPS_IP>/mcp/officer/health`
- **OAuth Discovery & JWKS**:
  - `http://<VPS_IP>/.well-known/oauth-authorization-server`
  - `http://<VPS_IP>/.well-known/jwks.json`
- **Program Token Authentication**: Generating admin tokens at `/admin/tokens` and invoking tools via Bearer auth.
- **Loopback OAuth Authorization**: Native/desktop clients with `http://localhost:<port>/callback` redirect URIs.

### What Requires HTTPS (A Real Domain):
- **External OAuth Dynamic Client Registration**: RFC 7591 / RFC 8252 requires non-loopback `redirect_uris` to use the `https` scheme. Plain `http://<external-domain-or-ip>/callback` is rejected with `invalid_redirect_uri`.
- **Client ID Metadata Documents (CIMD)**: Third-party client IDs using HTTPS URLs (`https://...`).
- **Production Cookie Security**: `Secure` cookie flags.

### Smoke Test Verification Commands:
```bash
# 1. Check portal health
curl -s http://localhost/health | jq .

# 2. Check Citizen MCP health (proxied)
curl -s http://localhost/mcp/health | jq .

# 3. Check Officer MCP health (proxied)
curl -s http://localhost/mcp/officer/health | jq .

# 4. Check OAuth 2.1 metadata
curl -s http://localhost/.well-known/oauth-authorization-server | jq .

# 5. Check JWKS endpoint
curl -s http://localhost/.well-known/jwks.json | jq .

# 6. Verify scheduler is genuinely absent
docker ps | grep scheduler || echo "[PASS] Scheduler is NOT running."
```

---

## 6. Backups, Restore & Rollback Procedures

### Manual Backup
```bash
./deploy/backup.sh
```

### Database Restore
```bash
./deploy/restore.sh ./backups/sewasetu_YYYYMMDD_HHMMSS.sql.gz
```

### Rollback
```bash
docker compose -f docker-compose.prod.yml down
# Revert git commit if needed
# Restore database snapshot if schema was altered
docker compose -f docker-compose.prod.yml up -d
```
