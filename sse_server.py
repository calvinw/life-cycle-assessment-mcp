"""
sse_server.py — FastAPI + FastMCP server for the Life Cycle Assessment MCP.

Exposes two interfaces on port 9000:
  /mcp  (SSE)  — MCP endpoint for Claude and other AI clients
  /api/*       — REST endpoints for programmatic / browser access
  /docs        — auto-generated OpenAPI docs (FastAPI)

Usage:
    python3 sse_server.py
"""

import os
import json
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from lca_server import mcp
from lca_engine import run_analysis, list_methods, check_brightway
from lca_svg_engine import generate_svg, generate_unit_process_svg

_CASE_STUDIES_DIR = pathlib.Path(__file__).parent / "case_studies"

# ── MCP http app (SSE transport) ──────────────────────────────────────────────

mcp_http = mcp.http_app(transport="sse", path="/mcp")

# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_http.lifespan(app):
        yield

app = FastAPI(
    title="Life Cycle Assessment API",
    description="LCA calculation server powered by Brightway 2.5. "
                "Also available as an MCP server at /mcp for AI clients.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-api-key"],
    expose_headers=["Content-Type", "Authorization", "x-api-key"],
    max_age=86400,
)

# Required for MCP remote client discovery
@app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def oauth_metadata():
    return JSONResponse({"issuer": ""})

# Mount MCP server
app.mount("/mcp", mcp_http)


# ── REST — health ─────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["server"])
def api_health():
    """Brightway engine health check."""
    return check_brightway()


# ── REST — methods ────────────────────────────────────────────────────────────

@app.get("/api/methods", tags=["lca"])
def api_list_methods():
    """List all LCIA methods available in the Brightway project."""
    return list_methods()


# ── REST — case studies ───────────────────────────────────────────────────────

@app.get("/api/case-studies", tags=["case-studies"])
def api_list_case_studies():
    """List bundled teaching case studies."""
    return [p.stem for p in sorted(_CASE_STUDIES_DIR.glob("*.md"))]


@app.get("/api/case-studies/{name}", tags=["case-studies"])
def api_get_case_study(name: str):
    """Return the pre-computed bundle for a named case study."""
    bundle_path = _CASE_STUDIES_DIR / f"{name}.json"
    if bundle_path.exists():
        return json.loads(bundle_path.read_text())
    md_path = _CASE_STUDIES_DIR / f"{name}.md"
    if md_path.exists():
        return {"recipe_card": md_path.read_text()}
    available = [p.stem for p in _CASE_STUDIES_DIR.glob("*.md")]
    raise HTTPException(
        status_code=404,
        detail=f"Case study '{name}' not found. Available: {available}",
    )


# ── REST — LCA calculation ────────────────────────────────────────────────────

class RunLcaRequest(BaseModel):
    recipe_card: str


class SvgRequest(BaseModel):
    recipe_card: str
    graph_type: str = "scaled"


class UnitProcessSvgRequest(BaseModel):
    recipe_card: str
    process_name: str


@app.post("/api/lca/run", tags=["lca"])
def api_run_lca(body: RunLcaRequest):
    """
    Run a full LCA from a recipe card YAML string.

    Returns LCI totals, LCIA scores, scaling vector, and SVG diagrams.
    """
    try:
        result = run_analysis(body.recipe_card)
        result["svg_scaled"]    = generate_svg(body.recipe_card, "scaled")
        result["svg_structure"] = generate_svg(body.recipe_card, "structure")
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/lca/svg", tags=["lca"])
def api_get_svg(body: SvgRequest):
    """Generate a supply chain SVG diagram from a recipe card."""
    try:
        return {"svg": generate_svg(body.recipe_card, body.graph_type)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/lca/svg/unit-process", tags=["lca"])
def api_get_unit_process_svg(body: UnitProcessSvgRequest):
    """Generate a unit process card SVG for one named process."""
    try:
        return {"svg": generate_unit_process_svg(body.recipe_card, body.process_name)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9000))
    uvicorn.run(app, host="0.0.0.0", port=port)
