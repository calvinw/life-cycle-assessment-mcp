"""
sse_server.py — HTTP entry point for the Life Cycle Assessment MCP server.

Runs FastMCP directly (same pattern as MacFLStudioMCP) so that FastMCP owns
the uvicorn server and handles all routing including the MCP endpoint.

MCP endpoint: /mcp  (Streamable HTTP — MCP spec 2025-03-26)
REST API:     /api/* (custom routes registered in lca_server.py)

Usage:
    python3 sse_server.py
"""

import os

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from lca_server import mcp

CORS_MIDDLEWARE = [
    Middleware(
        CORSMiddleware,
        allow_origins=[
            "https://calvinw.github.io",
            "http://localhost:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9000))
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        middleware=CORS_MIDDLEWARE,
    )
