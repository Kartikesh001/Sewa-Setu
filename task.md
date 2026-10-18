# Sewa Setu AI Assistant — Task Tracker

## 1. Project Overview
Build two distinct Model Context Protocol (MCP) servers over streamable HTTP for the Department of Social Welfare, Government of Purvanchal's Old Age Pension Portal (**Sewa Setu**):
1. **Citizen / Applicant MCP Server (`/mcp/citizen`)**
2. **Block Officer MCP Server (`/mcp/officer`)**

The existing portal (`app/`), database, and SMS gateway (`smsgw/`) remain the single system of record and are kept unmodified.

---

## 2. Checklist & Progress

### Phase 1: Environment & Architecture Planning
- [x] Listen to and transcribe `DIRECTOR-NOTE.mp3`
- [x] Analyze `BRIEF.md`, `README.md`, database schema, and OAuth 2.1 specifications
- [x] Create project task tracking document (`task.md`)
- [x] Install MCP Python SDK (`mcp[cli]`, `sse-starlette`, `httpx`)

### Phase 2: Citizen MCP Server (`citizen_mcp/`)
- [x] Implement standalone Citizen MCP Server over Streamable HTTP (SSE)
- [x] Connect to PostgreSQL database & read `config/app.ini` without modifying existing core files
- [x] Implement OAuth 2.1 token verification (RS256 JWT, JWKS, `aud`, `iss`, `scope: citizen`, extract `sub: citizen:<mobile>`)
- [x] Implement Citizen Tools:
  - [x] `get_scheme_guidelines`: Authoritative facts (₹250/mo, 60+ age, Sonari/Rajapara/Dhemaji Pathar/Borgaon/Namti/Khelua, 15-day SLA)
  - [x] `check_eligibility`: Validate age (in IST) and block residency
  - [x] `check_existing_application`: Query live application for authenticated mobile
  - [x] `submit_pension_application`: Full validation (format, age, IFSC, bank account, age-proof doc), DB insert, portal user creation, audit logging, SMS notification
  - [x] `get_my_application_status`: Real-time status, days pending against 15-day statutory SLA, decision details
  - [x] `withdraw_pending_application`: Withdraw pending application to allow re-applying
- [x] Test Citizen MCP server module and verify tool execution

### Phase 3: Block Officer MCP Server (`officer_mcp/`)
- [x] Implement standalone Block Officer MCP Server over Streamable HTTP (SSE)
- [x] Enforce OAuth 2.1 scope: `officer` or admin program token, extract `sub: officer:<username>`
- [x] Implement Officer Tools:
  - [x] `get_queue_summary`: Overview of pending, urgent (< 3 days SLA remaining), and decided applications
  - [x] `list_pending_applications`: Filter by block, sort by SLA urgency or date
  - [x] `get_application_dossier`: Full applicant details, document path, audit trail
  - [x] `approve_application`: Approve application, record officer identity, timestamp, audit log, SMS
  - [x] `reject_application`: Reject application with mandatory note, audit log, SMS
- [x] Test Officer MCP server with local MCP client / test suite

### Phase 4: Persona & Evaluation Engine
- [ ] Create 6 realistic citizen & officer personas:
  - [ ] Persona 1: Hemaprabha Devi (71, Sonari) — illiterate widow guided by grandson; eligible; full flow
  - [ ] Persona 2: Biren Gogoi (57, Borgaon) — underage applicant ($< 60$); assistant politely declines
  - [ ] Persona 3: Minoti Saikia (66, Namti) — bank passbook typo; assistant catches bad IFSC/account and guides correction
  - [ ] Persona 4: Purna Borah (68, Khelua) — duplicate application check; informs of active pending case
  - [ ] Persona 5: Kamala Das (64, Rajapara) — withdrawal and re-application flow
  - [ ] Persona 6: Block Officer Review — reviewing and approving pending applications
- [ ] Implement automated evaluation runner (`evals/runner.py`) asserting DB state, audit log, and SMS gateway

### Phase 5: Evaluation Dashboard (`/eval-dashboard`)
- [ ] Build interactive web dashboard displaying:
  - [ ] Overview metrics (pass rate, turn count, SLA tracking)
  - [ ] Persona cards & background context
  - [ ] Turn-by-turn conversation transcripts
  - [ ] Database assertion diffs (before vs. after)
  - [ ] Live re-run trigger

### Phase 6: Submissions & Documentation
- [ ] Draft 1-page Design Note (3 crucial decisions + 1 alternative)
- [ ] Prepare 3-minute Loom video script (face + screen)
- [ ] Deployment package verification (Docker / VM HTTPS)
