# REST API

The REST API exposes the same 13 domain operations as the MCP server. Use
`GET /api/tools` to discover each operation's description, JSON input and
output schemas, and equivalent HTTP method and path.

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
