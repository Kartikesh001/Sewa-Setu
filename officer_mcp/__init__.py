"""
Sewa Setu Block Officer MCP Package
"""

try:
    from .server import mcp_server, create_asgi_app
except ImportError:
    mcp_server = None
    create_asgi_app = None

__all__ = ["mcp_server", "create_asgi_app"]
