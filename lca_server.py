"""
lca_server.py — Life Cycle Assessment MCP server (Brightway 2.5 engine).

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

from lca_engine import run_analysis, list_methods, check_brightway, _ensure_databases, query_database, get_database_schema
from lca_engine import list_databases as _list_databases
from lca_engine import search_database as _search_database
from lca_search import get_activity_inputs as _get_activity_inputs
from lca_svg_engine import generate_svg, generate_unit_process_svg
from scripts.bafu_graph_svg import generate_bafu_svg as _generate_bafu_svg

mcp = FastMCP("Life Cycle Assessment MCP")

# Download BAFU database tarball on startup if not already present
_ensure_databases()

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
    result = run_analysis(product_graph)
    result["svg_scaled"]    = generate_svg(product_graph, "scaled")
    result["svg_structure"] = generate_svg(product_graph, "structure")
    return result


@mcp.tool()
def get_lca_svg(product_graph: str, graph_type: str = "scaled") -> str:
    """
    Generate a supply chain SVG diagram from a product graph YAML string.

    graph_type: "scaled"    — shows flow amounts and scaling factors
                "structure" — shows flow names only
    Returns SVG as a string.
    """
    return generate_svg(product_graph, graph_type)


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
    import bw2data as bd
    import tempfile, pathlib

    bd.projects.set_current("lca_server")
    matches = [m for m in bd.methods
               if m[0] == method_name and method_category.lower() in m[1].lower()]
    if not matches:
        raise ValueError(
            f"No method found for '{method_name}' / '{method_category}'. "
            f"Use list_impact_methods() to browse available methods."
        )
    method = matches[0]

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        out_path = f.name

    _generate_bafu_svg(
        activity_name=activity_name,
        location=location,
        method=method,
        output_path=out_path,
        max_depth=max_depth,
        cutoff=cutoff,
        database=database,
    )
    svg = pathlib.Path(out_path).read_text()
    pathlib.Path(out_path).unlink()
    return svg


@mcp.tool()
def get_lca_database_schema() -> dict:
    """
    Return the schema and freshness of the searchable SQLite projection.

    Call this before writing SQL queries with query_lca_database() to understand
    the available typed columns, views, and endpoint direction. This tool does
    not expose Brightway's internal databases.db file.
    """
    return get_database_schema()


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
    return query_database(sql, limit=limit)


@mcp.tool()
def get_unit_process_svg(product_graph: str, process_name: str) -> str:
    """
    Generate a unit process card SVG for one named process in the supply chain.

    process_name must match a process name in the product graph exactly,
    e.g. "P1 — Sheep farming" or "P2 — Wool yarn production".
    Returns SVG as a string.
    """
    return generate_unit_process_svg(product_graph, process_name)


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
    return _list_databases()


@mcp.tool()
def search_database(query: str, database: str = "biosphere3", limit: int = 25) -> list:
    """
    Full-text search for flows or activities in the SQLite search projection.

    Searches names, reference products, comments, categories, classifications,
    and synonyms. Returns the Brightway (database, code) key for authoritative
    lookup by run_lca. It never queries Brightway's internal databases.db file.
    """
    return _search_database(query, database=database, limit=limit)


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
    return _get_activity_inputs(
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
        result = run_analysis(product_graph)
        result["svg_scaled"]    = generate_svg(product_graph, "scaled")
        result["svg_structure"] = generate_svg(product_graph, "structure")
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@mcp.custom_route("/api/lca/svg", methods=["POST"])
async def api_get_svg(request: Request) -> Response:
    try:
        body = await request.json()
        return JSONResponse({"svg": generate_svg(body["product_graph"], body.get("graph_type", "scaled"))})
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


@mcp.custom_route("/api/lca/svg/unit-process", methods=["POST"])
async def api_get_unit_process_svg(request: Request) -> Response:
    try:
        body = await request.json()
        return JSONResponse({"svg": generate_unit_process_svg(body["product_graph"], body["process_name"])})
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)


# ── Entry point (stdio) ───────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
