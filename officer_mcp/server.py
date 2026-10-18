"""
Block Officer MCP Server for Sewa Setu Old Age Pension.
Streamable HTTP / SSE Model Context Protocol server for Block Development Officers,
Social Welfare Officers, and departmental decision-makers.
"""

import os
import sys
import uvicorn
from mcp.server.mcpserver import MCPServer

try:
    from .config import OFFICER_MCP_HOST, OFFICER_MCP_PORT
    from .tools import (
        get_queue_summary,
        list_pending_applications,
        get_application_dossier,
        approve_application,
        reject_application
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from officer_mcp.config import OFFICER_MCP_HOST, OFFICER_MCP_PORT
    from officer_mcp.tools import (
        get_queue_summary,
        list_pending_applications,
        get_application_dossier,
        approve_application,
        reject_application
    )

INSTRUCTIONS = """
You are the official Sewa Setu Block Officer Assistant for the Department of Social Welfare, Government of Purvanchal.
Your duty is to assist Block Development Officers and Social Welfare Officers to:
1. Efficiently inspect and manage their review queues without needing to click through dozens of web pages.
2. Prioritize applications approaching the statutory 15-day SLA deadline (< 3 days remaining) to prevent automatic deemed approval.
3. Review detailed applicant dossiers, including age eligibility, resident blocks, bank details, and audit histories.
4. Record formal approvals with optional officer notes, updating the database, generating audit log entries, and triggering SMS notifications.
5. Record formal rejections with mandatory plain-language justification, logging audit records, and notifying applicants by SMS.

Security Rules:
- You ONLY have access to Block Officer tools. You cannot submit citizen applications or bypass authentication.
- All actions require a verified OAuth 2.1 token with 'officer' scope.
- Rejection reasons are legally required under the Purvanchal Right to Public Services Act. Never submit a blank reason.
- Be precise, audit-conscious, and maintain strict data privacy.
"""

# Initialize MCP Server
mcp_server = MCPServer(
    name="sewasetu-officer-assistant",
    instructions=INSTRUCTIONS,
    version="1.0.0"
)

# Register Officer Tools (5 tools)
mcp_server.tool()(get_queue_summary)
mcp_server.tool()(list_pending_applications)
mcp_server.tool()(get_application_dossier)
mcp_server.tool()(approve_application)
mcp_server.tool()(reject_application)


@mcp_server.custom_route("/", methods=["GET"])
async def root_status(request):
    """Browser-friendly status page explaining Block Officer MCP endpoints."""
    from starlette.responses import HTMLResponse
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Sewa Setu — Block Officer MCP Server</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px auto; max-width: 800px; line-height: 1.6; color: #1e293b; background: #f8fafc; }
        .card { background: white; padding: 32px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); border: 1px solid #e2e8f0; }
        .badge { display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 600; background: #e0e7ff; color: #3730a3; }
        h1 { color: #0f172a; margin-top: 0; }
        pre { background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 14px; }
        ul { padding-left: 20px; }
        li { margin-bottom: 8px; }
        code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">● Officer Server Online</span>
        <h1>Sewa Setu — Block Officer MCP Server</h1>
        <p>This is the official <strong>Model Context Protocol (MCP) Streamable HTTP</strong> endpoint for Block Development Officers and Social Welfare Officers.</p>
        
        <h3>🤖 Connecting AI Clients (Claude Code, Cursor, Windsurf):</h3>
        <p>AI clients talk to this server using the Model Context Protocol over streamable HTTP at <code>/mcp/officer</code>:</p>
        <pre>claude mcp add sewasetu-officer -- http://localhost:8002/mcp/officer</pre>
        
        <h3>🛠 Registered Officer Tools (5 available):</h3>
        <ul>
            <li><code>get_queue_summary</code> — High-level overview of pending, SLA-critical (< 3 days), and decided applications.</li>
            <li><code>list_pending_applications</code> — Filter pending applications by block and sort by SLA urgency.</li>
            <li><code>get_application_dossier</code> — Complete applicant dossier, bank account, document path, and chronological audit log.</li>
            <li><code>approve_application</code> — Formally approve application, record officer ID &amp; timestamp in audit log, and send SMS.</li>
            <li><code>reject_application</code> — Formally reject application with mandatory reason, record audit log, and send SMS.</li>
        </ul>
        
        <p><small>Department of Social Welfare, Government of Purvanchal &middot; Streamable HTTP MCP 2.x</small></p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@mcp_server.custom_route("/health", methods=["GET"])
async def health_check(request):
    """JSON health check endpoint."""
    from starlette.responses import JSONResponse
    return JSONResponse({
        "status": "healthy",
        "service": "sewasetu-officer-assistant",
        "mcp_endpoint": "/mcp/officer",
        "transport": "streamable-http",
        "tools_count": 5
    })


def create_asgi_app():
    """Create ASGI application for Streamable HTTP transport supporting both /mcp/officer and /mcp."""
    app = mcp_server.streamable_http_app(streamable_http_path="/mcp/officer")
    app.add_route("/", root_status, methods=["GET"])
    app.add_route("/health", health_check, methods=["GET"])
    app.add_route("/mcp/officer/health", health_check, methods=["GET"])
    return app


def main():
    """Run the Block Officer MCP server over streamable HTTP."""
    port = int(os.environ.get("OFFICER_MCP_PORT", OFFICER_MCP_PORT))
    host = os.environ.get("OFFICER_MCP_HOST", OFFICER_MCP_HOST)
    print(f"Starting Sewa Setu Block Officer MCP Server on http://{host}:{port}/mcp/officer ...")
    app = create_asgi_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
