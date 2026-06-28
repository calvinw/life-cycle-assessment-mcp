"""
lca_server.py — Life Cycle Assessment MCP server (Brightway 2.5 engine).

MCP Tools:
    run_lca              — full LCA from a recipe card YAML string
    get_lca_svg          — supply chain diagram (scaled or structure)
    get_unit_process_svg — single-process card SVG
    list_impact_methods  — list all LCIA methods loaded in Brightway
    check_server         — Brightway engine health check
    list_case_studies    — list bundled teaching case studies
    get_case_study       — return the pre-computed bundle for a named case study

REST API (via @mcp.custom_route):
    GET  /api/health
    GET  /api/methods
    GET  /api/case-studies
    GET  /api/case-studies/{name}
    POST /api/lca/run
    POST /api/lca/svg
    POST /api/lca/svg/unit-process

Run via HTTP (for Claude.ai / cloudflared):
    python3 sse_server.py

Run in stdio mode:
    python3 lca_server.py
"""

import json
import pathlib

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastmcp import FastMCP

from lca_engine import run_analysis, list_methods, check_brightway, _ensure_databases
from lca_engine import list_databases as _list_databases
from lca_engine import search_database as _search_database
from lca_svg_engine import generate_svg, generate_unit_process_svg

mcp = FastMCP("Life Cycle Assessment MCP")

# Download BAFU database tarball on startup if not already present
_ensure_databases()

_CASE_STUDIES_DIR = pathlib.Path(__file__).parent / "case_studies"


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def run_lca(recipe_card: str) -> dict:
    """
    Run a full LCA from a recipe card YAML string.

    Returns LCI totals, LCIA impact scores, scaling vector, and two SVG
    supply chain diagrams (svg_scaled and svg_structure). The recipe card
    is the YAML frontmatter from a recipe_card.md file (with or without
    the --- fence markers).
    """
    result = run_analysis(recipe_card)
    result["svg_scaled"]    = generate_svg(recipe_card, "scaled")
    result["svg_structure"] = generate_svg(recipe_card, "structure")
    return result


@mcp.tool()
def get_lca_svg(recipe_card: str, graph_type: str = "scaled") -> str:
    """
    Generate a supply chain SVG diagram from a recipe card YAML string.

    graph_type: "scaled"    — shows flow amounts and scaling factors
                "structure" — shows flow names only
    Returns SVG as a string.
    """
    return generate_svg(recipe_card, graph_type)


@mcp.tool()
def get_unit_process_svg(recipe_card: str, process_name: str) -> str:
    """
    Generate a unit process card SVG for one named process in the supply chain.

    process_name must match a process name in the recipe card exactly,
    e.g. "P1 — Sheep farming" or "P2 — Wool yarn production".
    Returns SVG as a string.
    """
    return generate_unit_process_svg(recipe_card, process_name)


@mcp.tool()
def list_case_studies() -> list:
    """
    List the bundled teaching case studies available on this server.
    Each name can be passed to get_case_study() to retrieve the full bundle.
    """
    return [p.stem for p in sorted(_CASE_STUDIES_DIR.glob("*.md"))]


@mcp.tool()
def get_case_study(name: str) -> dict:
    """
    Return the pre-computed bundle for a named case study.

    The bundle contains:
        recipe_card       — full recipe card YAML text
        svg_structure     — supply chain diagram (flow names only) as SVG string
        svg_scaled        — supply chain diagram (with amounts) as SVG string
        unit_process_svgs — dict of process_name → SVG string
        lca_results       — dict with keys: name, method, functional_unit,
                            lci, lcia, scaling_vector

    Use list_case_studies() to see available names.
    """
    bundle_path = _CASE_STUDIES_DIR / f"{name}.json"
    if bundle_path.exists():
        return json.loads(bundle_path.read_text())
    md_path = _CASE_STUDIES_DIR / f"{name}.md"
    if md_path.exists():
        return {"recipe_card": md_path.read_text()}
    available = [p.stem for p in _CASE_STUDIES_DIR.glob("*.md")]
    raise ValueError(f"Case study '{name}' not found. Available: {available}")


@mcp.tool()
def list_databases() -> list:
    """
    List all databases installed in the current Brightway project,
    with size, backend, and dependencies.
    """
    return _list_databases()


@mcp.tool()
def search_database(query: str, database: str = "biosphere3", limit: int = 25) -> list:
    """
    Search for flows or activities in a named Brightway database.

    Returns matching entries with name, categories, unit, type, and key.
    Use list_databases() to see available database names.
    """
    return _search_database(query, database=database, limit=limit)


@mcp.tool()
def list_impact_methods() -> list:
    """
    List all LCIA methods available in the Brightway project.
    Returns a list of dicts with name and categories.
    """
    return list_methods()


@mcp.tool()
def check_server() -> dict:
    """Check that the Brightway LCA engine is initialised and ready."""
    return check_brightway()


# ── REST API (custom routes — available when running via HTTP transport) ───────

@mcp.custom_route("/api/health", methods=["GET"])
async def api_health(request: Request) -> Response:
    return JSONResponse(check_brightway())


@mcp.custom_route("/api/methods", methods=["GET"])
async def api_list_methods(request: Request) -> Response:
    return JSONResponse(list_methods())


@mcp.custom_route("/api/case-studies", methods=["GET"])
async def api_list_case_studies(request: Request) -> Response:
    return JSONResponse([p.stem for p in sorted(_CASE_STUDIES_DIR.glob("*.md"))])


@mcp.custom_route("/api/case-studies/{name}", methods=["GET"])
async def api_get_case_study(request: Request) -> Response:
    name = request.path_params["name"]
    bundle_path = _CASE_STUDIES_DIR / f"{name}.json"
    if bundle_path.exists():
        return JSONResponse(json.loads(bundle_path.read_text()))
    md_path = _CASE_STUDIES_DIR / f"{name}.md"
    if md_path.exists():
        return JSONResponse({"recipe_card": md_path.read_text()})
    available = [p.stem for p in _CASE_STUDIES_DIR.glob("*.md")]
    return JSONResponse(
        {"detail": f"Case study '{name}' not found. Available: {available}"},
        status_code=404,
    )


@mcp.custom_route("/api/lca/run", methods=["POST"])
async def api_run_lca(request: Request) -> Response:
    try:
        body = await request.json()
        recipe_card = body["recipe_card"]
        result = run_analysis(recipe_card)
        result["svg_scaled"]    = generate_svg(recipe_card, "scaled")
        result["svg_structure"] = generate_svg(recipe_card, "structure")
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@mcp.custom_route("/api/lca/svg", methods=["POST"])
async def api_get_svg(request: Request) -> Response:
    try:
        body = await request.json()
        return JSONResponse({"svg": generate_svg(body["recipe_card"], body.get("graph_type", "scaled"))})
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@mcp.custom_route("/api/lca/svg/unit-process", methods=["POST"])
async def api_get_unit_process_svg(request: Request) -> Response:
    try:
        body = await request.json()
        return JSONResponse({"svg": generate_unit_process_svg(body["recipe_card"], body["process_name"])})
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


# ── Entry point (stdio) ───────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
