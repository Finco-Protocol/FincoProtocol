"""FINCO MCP V1 — entry point.

Run with:
  FINCO_SESSION_TOKEN=<signed-token> python main_mcp.py

Or via stdio (default MCP transport):
  FINCO_SESSION_TOKEN=<signed-token> python main_mcp.py --transport stdio

Auth: FINCO_SESSION_TOKEN must be a valid signed session token produced by
app.auth.create_session_token() (admin) or app.auth.create_demo_session_token() (demo).
"""
from app.mcp.v1.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
