"""MCP and HTTP adapter for the transport-independent :mod:`lca_core` engine.

MCP Tools:
    run_lca              — full LCA from a product graph YAML string
    get_lca_svg          — supply chain diagram (scaled or structure)
    get_unit_process_svg — single-process card SVG
    list_impact_methods  — list all LCIA methods loaded in Brightway
    search_database      — full-text search of the inventory projection
    query_lca_database   — safe read-only SQL on the inventory projection
    get_lca_activity_inputs — typed direct exchanges for one activity
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

from lca_core import LCAEngine

mcp = FastMCP("Life Cycle Assessment MCP")
engine = LCAEngine()

# Download BAFU database tarball on startup if not already present
engine.ensure_ready()

_CASE_STUDIES_DIR = pathlib.Path(__file__).parent / "case_studies"


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def run_lca(product_graph: str) -> dict:
    """
    Run a full LCA from a product graph YAML string.

    Returns LCI totals, LCIA impact scores, scaling vector, and two SVG
    supply chain diagrams (svg_scaled and svg_structure). The product graph
    is the contents of a product_graph.yaml file.
    """
    return engine.run(product_graph, include_visuals=True)


@mcp.tool()
def get_lca_svg(product_graph: str, graph_type: str = "scaled") -> str:
    """
    Generate a supply chain SVG diagram from a product graph YAML string.

    graph_type: "scaled"    — shows flow amounts and scaling factors
                "structure" — shows flow names only
    Returns SVG as a string.
    """
    return engine.generate_svg(product_graph, graph_type)


@mcp.tool()
def get_bafu_svg(
    activity_name: str,
    location: str,
    method_name: str = "EF v3.1",
    method_category: str = "climate change",
    max_depth: int = 4,
    cutoff: float = 0.01,
    database: str = "bafu",
) -> str:
    """
    Generate a supply chain SVG for any BAFU background process.

    Shows the upstream supply chain with cumulative impact scores and
    contribution percentages at each node, traversed via bw_graph_tools.

    activity_name:   exact process name, e.g. "Polylactide, granulate, at plant"
    location:        location code, e.g. "GLO", "RER", "CH"
    method_name:     top-level LCIA method, e.g. "EF v3.1", "ReCiPe 2016 Midpoint (H)"
    method_category: impact category substring, e.g. "climate change", "acidification"
    max_depth:       how many levels deep to traverse (default 4)
    cutoff:          minimum fraction of total score to show a node (default 0.01 = 1%)
    database:        Brightway database name (default "bafu")

    Returns SVG as a string.
    """
    return engine.generate_background_svg(
        activity_name=activity_name,
        location=location,
        method_name=method_name,
        method_category=method_category,
        max_depth=max_depth,
        cutoff=cutoff,
        database=database,
    )


@mcp.tool()
def get_lca_database_schema() -> dict:
    """
    Return the exact public DDL, freshness, and query contract of the searchable
    SQLite projection.

    The schema_objects list contains the live CREATE statements for every
    supported table, virtual FTS table, view, and explicit index. Call this
    before writing SQL with query_lca_database(). This tool describes the
    separate search.sqlite3 projection, never Brightway's internal databases.db
    file. FTS5 shadow tables and SQLite auto-indexes are excluded because they
    are storage internals, not supported query surfaces.
    """
    return engine.get_database_schema()


@mcp.tool()
def query_lca_database(sql: str, limit: int = 100) -> dict:
    """
    Run read-only SQL against the searchable inventory projection.

    Available tables:
      activities        — processes and flows with searchable metadata
      exchanges         — typed amounts, units, endpoints, and uncertainty
      exchange_details  — exchanges joined to readable endpoint metadata
      activities_fts    — FTS5 index over names, products, comments, and tags

    Example queries:
      SELECT name, location FROM activities WHERE database='bafu' AND name LIKE '%cotton%'
      SELECT input_name, amount, unit FROM exchange_details WHERE output_database='bafu' AND output_code='<code>' AND exchange_type='technosphere'
      SELECT consumer_name, amount, unit FROM exchange_details WHERE input_database='bafu' AND input_code='<code>'

    Exchange amounts are direct inventory values, not LCIA scores. Only one
    SELECT/CTE statement is permitted. Results include freshness and truncation.
    """
    return engine.query_database(sql, limit=limit)


@mcp.tool()
def get_unit_process_svg(product_graph: str, process_name: str) -> str:
    """
    Generate a unit process card SVG for one named process in the supply chain.

    process_name must match a process name in the product graph exactly,
    e.g. "P1 — Sheep farming" or "P2 — Wool yarn production".
    Returns SVG as a string.
    """
    return engine.generate_unit_process_svg(product_graph, process_name)


@mcp.tool()
def list_case_studies() -> list:
    """
    List the bundled teaching case studies available on this server.
    Each name can be passed to get_case_study() to retrieve the full bundle.
    """
    return [p.stem for p in sorted(_CASE_STUDIES_DIR.glob("*.yaml"))]


@mcp.tool()
def get_case_study(name: str) -> dict:
    """
    Return the pre-computed bundle for a named case study.

    The bundle contains:
        product_graph       — full product graph YAML text
        svg_structure     — supply chain diagram (flow names only) as SVG string
        svg_scaled        — supply chain diagram (with amounts) as SVG string
        unit_process_svgs — dict of process_name → SVG string

    LCA results are not pre-computed here — pass product_graph to run_lca() to compute them.

    Use list_case_studies() to see available names.
    """
    bundle_path = _CASE_STUDIES_DIR / f"{name}.json"
    if bundle_path.exists():
        return json.loads(bundle_path.read_text())
    yaml_path = _CASE_STUDIES_DIR / f"{name}.yaml"
    if yaml_path.exists():
        return {"product_graph": yaml_path.read_text()}
    available = [p.stem for p in _CASE_STUDIES_DIR.glob("*.yaml")]
    raise ValueError(f"Case study '{name}' not found. Available: {available}")


@mcp.tool()
def list_databases() -> list:
    """
    List all databases installed in the current Brightway project,
    with size, backend, and dependencies.
    """
    return engine.list_databases()


@mcp.tool()
def search_database(query: str, database: str = "biosphere3", limit: int = 25) -> list:
    """
    Full-text search for flows or activities in the SQLite search projection.

    Searches names, reference products, comments, categories, classifications,
    and synonyms. Returns the Brightway (database, code) key for authoritative
    lookup by run_lca. It never queries Brightway's internal databases.db file.
    """
    return engine.search_activities(query, database=database, limit=limit)


@mcp.tool()
def get_lca_activity_inputs(
    database: str,
    code: str,
    exchange_type: str | None = None,
    limit: int = 500,
) -> list:
    """
    Return one activity's direct inputs from the SQLite search projection.

    database/code are the key returned by search_database(). exchange_type can
    be "technosphere", "biosphere", or "production"; omit it for all direct
    exchanges. Amounts are inventory quantities, not LCIA scores.
    """
    return engine.get_activity_inputs(
        database,
        code,
        exchange_type=exchange_type,
        limit=limit,
    )


@mcp.tool()
def list_impact_methods() -> list:
    """
    List all LCIA methods available in the Brightway project.
    Returns a list of dicts with name and categories.
    """
    return engine.list_methods()


@mcp.tool()
def check_server() -> dict:
    """Check that the Brightway LCA engine is initialised and ready."""
    return engine.check()


# ── REST API (custom routes — available when running via HTTP transport) ───────

@mcp.custom_route("/api/health", methods=["GET"])
async def api_health(request: Request) -> Response:
    return JSONResponse(engine.check())


@mcp.custom_route("/api/methods", methods=["GET"])
async def api_list_methods(request: Request) -> Response:
    return JSONResponse(engine.list_methods())


@mcp.custom_route("/api/case-studies", methods=["GET"])
async def api_list_case_studies(request: Request) -> Response:
    return JSONResponse([p.stem for p in sorted(_CASE_STUDIES_DIR.glob("*.yaml"))])


@mcp.custom_route("/api/case-studies/{name}", methods=["GET"])
async def api_get_case_study(request: Request) -> Response:
    name = request.path_params["name"]
    bundle_path = _CASE_STUDIES_DIR / f"{name}.json"
    if bundle_path.exists():
        return JSONResponse(json.loads(bundle_path.read_text()))
    yaml_path = _CASE_STUDIES_DIR / f"{name}.yaml"
    if yaml_path.exists():
        return JSONResponse({"product_graph": yaml_path.read_text()})
    available = [p.stem for p in _CASE_STUDIES_DIR.glob("*.yaml")]
    return JSONResponse(
        {"detail": f"Case study '{name}' not found. Available: {available}"},
        status_code=404,
    )


@mcp.custom_route("/api/lca/run", methods=["POST"])
async def api_run_lca(request: Request) -> Response:
    try:
        body = await request.json()
        product_graph = body["product_graph"]
        return JSONResponse(engine.run(product_graph, include_visuals=True))
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@mcp.custom_route("/api/lca/svg", methods=["POST"])
async def api_get_svg(request: Request) -> Response:
    try:
        body = await request.json()
        return JSONResponse({
            "svg": engine.generate_svg(
                body["product_graph"], body.get("graph_type", "scaled")
            )
        })
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@mcp.custom_route("/api/lca/svg/unit-process", methods=["POST"])
async def api_get_unit_process_svg(request: Request) -> Response:
    try:
        body = await request.json()
        return JSONResponse({
            "svg": engine.generate_unit_process_svg(
                body["product_graph"], body["process_name"]
            )
        })
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


# ── Entry point (stdio) ───────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
