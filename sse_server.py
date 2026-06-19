"""
sse_server.py — FastAPI SSE wrapper for the Life Cycle Assessment MCP.

Exposes the MCP over HTTP/SSE so any remote client (Claude.ai, ChatGPT,
Copilot, etc.) can call the LCA tools without a local install.

Usage:
    python3 sse_server.py

The MCP endpoint is at /sse.
"""

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from lca_server import mcp

http_app = mcp.http_app(transport="sse", path="/sse")


async def oauth_metadata(request: Request):
    return JSONResponse({"issuer": str(request.base_url).rstrip("/")})


app = FastAPI(lifespan=http_app.lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-api-key"],
)
app.add_api_route("/.well-known/oauth-authorization-server", oauth_metadata)
app.mount("/", http_app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 9000)))
