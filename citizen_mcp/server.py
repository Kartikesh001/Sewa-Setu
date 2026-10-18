"""
Citizen MCP Server for Sewa Setu Old Age Pension.
Streamable HTTP / SSE Model Context Protocol server for citizens,
family members, and CSC kiosk operators.
"""

import os
import sys
import uvicorn
from mcp.server.mcpserver import MCPServer

try:
    from .config import CITIZEN_MCP_HOST, CITIZEN_MCP_PORT
    from .tools import (
        get_scheme_guidelines,
        check_eligibility,
        check_my_application,
        submit_pension_application,
        get_my_application_status,
        withdraw_pending_application
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from citizen_mcp.config import CITIZEN_MCP_HOST, CITIZEN_MCP_PORT
    from citizen_mcp.tools import (
        get_scheme_guidelines,
        check_eligibility,
        check_my_application,
        submit_pension_application,
        get_my_application_status,
        withdraw_pending_application
    )

INSTRUCTIONS = """
You are the official Sewa Setu Citizen Pension Assistant for the Department of Social Welfare, Government of Purvanchal.
Your duty is to assist senior citizens, their relatives (such as grandchildren or daughters), and CSC kiosk operators to:
1. Understand official Old Age Pension rules and guidelines without guessing or hallucinating.
2. Check eligibility (minimum age 60, residents of Sonari, Rajapara, Dhemaji Pathar, Borgaon, Namti, Khelua).
3. Check existing applications to prevent duplicate filings.
4. Carefully collect required details (full name, date of birth DD/MM/YYYY, village, block, bank account 9-18 digits, IFSC 11 chars) and submit valid applications.
5. Track application status and statutory 15-day SLA deemed approval.
6. Assist with withdrawing mistaken pending applications so the citizen can re-apply.

Security Rules:
- You ONLY have access to citizen tools. You have no officer or administrative tools.
- All actions on behalf of a citizen must use their authenticated OAuth 2.1 token.
- Always be respectful, patient, and clear. Many applicants are elderly or non-literate.
"""

# Initialize MCP Server
mcp_server = MCPServer(
    name="sewasetu-citizen-assistant",
    instructions=INSTRUCTIONS,
    version="1.0.0"
)

# Register Tools
mcp_server.tool()(get_scheme_guidelines)
mcp_server.tool()(check_eligibility)
mcp_server.tool()(check_my_application)
mcp_server.tool()(submit_pension_application)
mcp_server.tool()(get_my_application_status)
mcp_server.tool()(withdraw_pending_application)


@mcp_server.custom_route("/", methods=["GET"])
async def root_status(request):
    """Browser-friendly status page explaining MCP endpoints."""
    from starlette.responses import HTMLResponse
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>Sewa Setu — Citizen MCP Server</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px auto; max-width: 800px; line-height: 1.6; color: #1e293b; background: #f8fafc; }
        .card { background: white; padding: 32px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); border: 1px solid #e2e8f0; }
        .badge { display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 600; background: #dcfce7; color: #15803d; }
        h1 { color: #0f172a; margin-top: 0; }
        pre { background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 14px; }
        ul { padding-left: 20px; }
        li { margin-bottom: 8px; }
        code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">● Online &amp; Ready</span>
        <h1>Sewa Setu — Citizen MCP Server</h1>
        <p>This is the official <strong>Model Context Protocol (MCP) Streamable HTTP</strong> endpoint for the Citizen Pension Assistant.</p>
        
        <h3>🤖 Connecting with Claude Code or AI Agent:</h3>
        <p>AI clients talk to this server using the Model Context Protocol over streamable HTTP at <code>/mcp</code>:</p>
        <pre>claude mcp add sewasetu-citizen -- http://localhost:8001/mcp</pre>
        
        <h3>🛠 Registered Tools (6 available):</h3>
        <ul>
            <li><code>get_scheme_guidelines</code> — Authoritative scheme facts directly from the department.</li>
            <li><code>check_eligibility</code> — Age and block residency validation.</li>
            <li><code>check_my_application</code> — Checks active applications for authenticated citizen.</li>
            <li><code>submit_pension_application</code> — Validates and inserts application into system of record.</li>
            <li><code>get_my_application_status</code> — Live tracking and 15-day statutory SLA countdown.</li>
            <li><code>withdraw_pending_application</code> — Withdraws mistaken pending application.</li>
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
        "service": "sewasetu-citizen-assistant",
        "mcp_endpoint": "/mcp",
        "transport": "streamable-http",
        "tools_count": 6
    })


def create_asgi_app():
    """Create ASGI application for Streamable HTTP transport with browser landing page."""
    app = mcp_server.streamable_http_app(streamable_http_path="/mcp")
    app.add_route("/", root_status, methods=["GET"])
    app.add_route("/health", health_check, methods=["GET"])
    app.add_route("/mcp/health", health_check, methods=["GET"])
    return app


def main():
    """Run the Citizen MCP server over streamable HTTP."""
    port = int(os.environ.get("CITIZEN_MCP_PORT", CITIZEN_MCP_PORT))
    host = os.environ.get("CITIZEN_MCP_HOST", CITIZEN_MCP_HOST)
    print(f"Starting Sewa Setu Citizen MCP Server on http://{host}:{port}/mcp ...")
    app = create_asgi_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
