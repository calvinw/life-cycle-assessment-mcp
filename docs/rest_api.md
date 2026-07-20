# REST API

The REST API exposes the same 13 domain operations as the MCP server. Use
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
| `get_lca_svg` | `POST /api/lca/svg` |
| `get_bafu_svg` | `POST /api/lca/svg/bafu` |
| `get_lca_database_schema` | `GET /api/database/schema` |
| `query_lca_database` | `POST /api/database/query` |
| `get_unit_process_svg` | `POST /api/lca/svg/unit-process` |
| `list_case_studies` | `GET /api/case-studies` |
| `get_case_study` | `GET /api/case-studies/{name}` |
| `list_databases` | `GET /api/databases` |
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

`POST /api/lca/run` is stateless. The YAML string in `product_graph` is the
complete calculation input; the server does not create sessions, retain
results, or require an identifier from an earlier request. Foreground
Brightway data is isolated for the request and removed after both successful
and failed calculations. Installed background databases are read-only
reference data shared by all requests.

The response retains the original LCI, LCIA, scaling-vector, and SVG fields and
adds schema-versioned contribution and Sankey data:

```json
{
  "result_schema_version": 2,
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
  }
}
```

Process scores are exclusive, preserve their sign, and reconcile with the
category total after adding `residual_score`. Background activity impact is
included in `residual_score`. Sankey amounts use the same solved scaling vector
as the rest of the response. Links retain their original units, so renderers
must compare widths only within compatible units.
