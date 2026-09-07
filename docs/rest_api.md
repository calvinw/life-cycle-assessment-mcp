# REST API

## Quick start

Base URL: `https://lca-mcp.mathplosion.com` (or `http://localhost:9000`
when running `python3 sse_server.py` locally with the default port).
The server's REST routes require no API key or MCP session. Send POST bodies
as JSON with `Content-Type: application/json`; responses are JSON too.

These shell examples require `curl` and `jq`:

```bash
BASE_URL=https://lca-mcp.mathplosion.com

# Check that the response says running: true.
curl -sS --fail-with-body "$BASE_URL/api/health" | jq

# Discover operations, required arguments, and defaults.
curl -sS --fail-with-body "$BASE_URL/api/tools" | jq

# Search background activities. Results are an array; key is [database, code].
curl -sS --fail-with-body "$BASE_URL/api/database/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"cotton","database":"bafu","limit":5}' | jq
```

To calculate an example, fetch the product-graph catalog and send its default
YAML document to the compact calculation endpoint:

```bash
curl -sS --fail-with-body "$BASE_URL/api/product-graphs" -o catalog.json
jq -e '{product_graph: (.default_id as $id | .product_graphs[] |
  select(.id == $id) | .product_graph)}' catalog.json > request.json

curl -sS --fail-with-body "$BASE_URL/api/lca/base" \
  -H 'Content-Type: application/json' \
  --data-binary @request.json -o result.json
jq '{result_id, lcia}' result.json
```

For your own YAML file, replace the catalog steps with:

```bash
jq -n --rawfile graph product.yaml '{product_graph: $graph}' > request.json
```

`product_graph` must be **YAML encoded as a JSON string**, not a nested JSON
object. `jq` handles newlines and quoting. Each `lcia` entry returns a `score`
and `unit`; only the categories requested in the YAML are calculated.

Use `/api/lca/base` for compact results, `/api/lca/run` to also calculate
configured contribution graphs, and `/api/lca/svg` for a diagram (JSON containing
an `svg` string). Calculations are stateless: send the complete YAML each time.
For failed POST requests, inspect the HTTP 400 body: `{"detail":"..."}`.

Browser calls are subject to CORS. The HTTP entry point currently allows
`https://calvinw.github.io` and `http://localhost:5173`; other frontend origins
need to be added in `sse_server.py`.

## Endpoint reference

The REST API exposes the same 16 domain operations as the MCP server. Use
`GET /api/tools` to discover each operation's description, JSON input schema,
MCP output schema, and equivalent HTTP method and path.

For exact REST response bodies, endpoint-selection guidance, and complete
examples intended for AI agents, see the [LLM REST API Guide](llm_rest_api_guide.md).

```bash
curl -s https://lca-mcp.mathplosion.com/api/tools | jq
```

## MCP-to-REST mapping

| MCP tool | REST operation |
| --- | --- |
| `run_lca` | `POST /api/lca/run` |
| `run_lca_base` | `POST /api/lca/base` |
| `get_lca_contribution_graphs` | `POST /api/lca/contribution` |
| `get_lca_svg` | `POST /api/lca/svg` |
| `get_bafu_svg` | `POST /api/lca/svg/bafu` |
| `get_lca_database_schema` | `GET /api/database/schema` |
| `query_lca_database` | `POST /api/database/query` |
| `get_unit_process_svg` | `POST /api/lca/svg/unit-process` |
| `list_case_studies` | `GET /api/case-studies` |
| `get_case_study` | `GET /api/case-studies/{name}` |
| `list_databases` | `GET /api/databases` |
| `list_product_graphs` | `GET /api/product-graphs` |
| `search_database` | `POST /api/database/search` |
| `get_lca_activity_inputs` | `POST /api/database/activity-inputs` |
| `list_impact_methods` | `GET /api/methods` |
| `check_server` | `GET /api/health` |

POST operations accept the same argument names and defaults as their MCP
counterparts. For example:

```bash
curl -s https://lca-mcp.mathplosion.com/api/database/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"cotton", "database":"bafu", "limit":5}' | jq
```

Errors from POST operations are returned as HTTP 400 responses with a JSON
body of the form `{"detail":"..."}`.

## Stateless LCA calculations

All LCA calculation endpoints are stateless. The YAML string in
`product_graph` is the complete calculation input; the server does not create
sessions or retain results. `POST /api/lca/base` returns a deterministic
`result_id`, which a client can send to `POST /api/lca/contribution` as a guard
against attaching a graph to results from different YAML. Foreground Brightway
data is isolated for each request and removed after both successful and failed
calculations. Installed background databases are read-only reference data
shared by all requests.

The bundled `mock_background` database has small, fictional product graphs for
internal testing, but these are intentionally excluded from the public case
study catalog. See [Tiny Mock Background Database](mock_background_database.md).

The compact base response contains LCI, LCIA, scaling-vector,
schema-versioned direct contribution, and Sankey data. Only the impact
categories explicitly listed in `lcia.categories` are calculated and returned.
The lazy contribution endpoint rejects categories outside that YAML list.
SVGs are generated only by the dedicated SVG endpoints:

```json
{
  "result_id": "sha256-of-normalized-product-graph",
  "result_schema_version": 3,
  "process_contributions": {
    "categories": [
      {
        "id": "impact:...",
        "label": "climate change | global warming potential (GWP100)",
        "unit": "kg CO2-Eq",
        "total_score": 2.535,
        "processes": [
          {
            "process_id": "process:...",
            "process_name": "P1 — Oil extraction",
            "direct_score": 0.435,
            "percentage": 17.16,
            "scope": "foreground"
          }
        ],
        "residual_score": 0
      }
    ]
  },
  "sankey": {
    "nodes": [],
    "links": [],
    "available_units": ["kg", "unit"]
  },
  "background_link_intensities": [
    {
      "link_id": "background-link:...",
      "process_index": 0,
      "input_index": 0,
      "process_name": "Plastic broom assembly",
      "flow": "Polylactide, granulate, at plant",
      "database": "bafu",
      "code": "273090",
      "location": "GLO",
      "amount": 0.52,
      "unit": "kg",
      "intensities": {
        "climate change | global warming potential (GWP100)": 2.7064573564136585
      }
    }
  ]
}
```

`background_link_intensities` is **optional**. The background intensity cache
is always on, so the field is normally present, but it is omitted whenever the
cache cannot supply every requested category — including after a runtime
failure disables the cache for the life of the process. Its absence is a normal
fallback and never an error, so clients must feature-detect it rather than
require it. `result_schema_version` stays `3`.

Each entry gives the cumulative LCIA intensity of the background activity behind
one foreground input, per calculated category. `process_index` and `input_index`
address the exchange in the submitted YAML and are the authoritative key; the
descriptive fields exist so a client can cross-check against its own parse. A
graph with no background inputs returns an empty list.

Because these are cumulative intensities, a client can rescore background input
edits locally without another request:

```text
score_new = score_baseline
          + Σ  scaling_vector[process_name] × (amount_new − amount) × intensity
```

This holds exactly while the foreground structure is unchanged, which is what
keeps `scaling_vector` valid. Editing an emission, a reference output, or a
provider invalidates it — recalculate instead.

Expect agreement with a full recalculation to about `1e-7` relative, not to
machine precision. Brightway stores technosphere amounts as float32, so the
server scores `0.52` as `0.5199999809265137` while a client multiplies the exact
value. Compare with a relative tolerance of `1e-6`, never for equality.

Process scores are exclusive, preserve their sign, include both foreground and
background activities, and reconcile with the category total after adding
`residual_score`. Sankey amounts use the same solved scaling vector as the rest
of the response. Links retain their original units, so renderers must compare
widths only within compatible units.
