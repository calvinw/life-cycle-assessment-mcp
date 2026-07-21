# LLM Guide to the Life Cycle Assessment REST API

This document is an operating guide for a language model or agent that can make
HTTP requests. It explains how to discover and call the Life Cycle Assessment
(LCA) REST API without using MCP.

## Connection

Use this base URL:

```text
https://lca-mcp.mathplosion.com
```

All responses are JSON. POST requests must include:

```http
Content-Type: application/json
```

The API currently requires no authentication. Do not send an MCP session ID to
REST routes. The MCP protocol endpoint is `/mcp`; REST clients should use only
the `/api/*` routes described here.

## Required startup sequence

Before doing LCA work, perform these calls in order:

1. Call `GET /api/health`.
2. Continue only when the response contains `"running": true`.
3. Call `GET /api/tools` to discover the current operations and input schemas.
4. Select the narrowest endpoint that answers the user's request.

Example:

```bash
curl -sS https://lca-mcp.mathplosion.com/api/health
curl -sS https://lca-mcp.mathplosion.com/api/tools
```

`GET /api/tools` returns one object per domain operation:

```json
{
  "name": "search_database",
  "description": "Full-text search for flows or activities...",
  "input_schema": {
    "properties": {
      "query": {"type": "string"},
      "database": {"default": "biosphere3", "type": "string"},
      "limit": {"default": 25, "type": "integer"}
    },
    "required": ["query"],
    "type": "object"
  },
  "output_schema": {"...": "MCP output schema"},
  "rest": {"method": "POST", "path": "/api/database/search"}
}
```

Treat `input_schema` and `rest` as the live source of truth for REST calls.
`output_schema` describes the equivalent MCP tool result. Some REST routes
return a more natural HTTP body—for example, REST SVG routes return
`{"svg":"<svg ...>"}` and REST list routes return a JSON array directly.
The exact REST bodies are documented below.

## Endpoint selection

| User intent | REST operation |
| --- | --- |
| Check availability | `GET /api/health` |
| Discover operations and arguments | `GET /api/tools` |
| Browse LCIA method families | `GET /api/methods` |
| List installed databases | `GET /api/databases` |
| Find an activity or flow by text | `POST /api/database/search` |
| Inspect one activity's direct exchanges | `POST /api/database/activity-inputs` |
| Learn the searchable SQL schema | `GET /api/database/schema` |
| Run a custom read-only query | `POST /api/database/query` |
| List teaching examples | `GET /api/case-studies` |
| Retrieve a teaching example | `GET /api/case-studies/{name}` |
| Calculate a product graph | `POST /api/lca/run` |
| Render a product graph | `POST /api/lca/svg` |
| Render one foreground unit process | `POST /api/lca/svg/unit-process` |
| Render a BAFU background supply chain | `POST /api/lca/svg/bafu` |

Prefer the typed search and activity-input endpoints over SQL when they satisfy
the request. Use the SQL endpoint for questions requiring joins, aggregation,
reverse-link lookup, or filtering not supported by typed endpoints.

## Endpoint contracts

### Health

```http
GET /api/health
```

Important response fields:

```json
{
  "running": true,
  "engine": "brightway2.5",
  "project": "lca_server",
  "databases": ["biosphere3", "bafu", "mock_background"],
  "methods": 1246,
  "search_database": {
    "exists": true,
    "fresh": true
  }
}
```

The `methods` number is the count of individual Brightway method/category
tuples. It is normally larger than the number of grouped families returned by
`GET /api/methods`.

### Impact methods

```http
GET /api/methods
```

Response: a JSON array of method families and their categories.

```json
[
  {
    "name": "AWARE",
    "categories": ["Water use"]
  }
]
```

Use an exact returned `name` as `lcia.method_name` in a product graph. For
`POST /api/lca/svg/bafu`, use a category substring from `categories` as
`method_category`.

### Installed databases

```http
GET /api/databases
```

Response:

```json
[
  {
    "name": "bafu",
    "size": 11947,
    "backend": "sqlite",
    "depends": ["biosphere3"]
  },
  {
    "name": "mock_background",
    "size": 3,
    "backend": "sqlite",
    "depends": ["biosphere3"]
  }
]
```

### Search activities and flows

```http
POST /api/database/search
Content-Type: application/json
```

Request:

```json
{
  "query": "cotton",
  "database": "bafu",
  "limit": 5
}
```

Only `query` is required. Defaults are `database="biosphere3"` and `limit=25`.
Use `database="bafu"` to search background processes.

Response:

```json
[
  {
    "name": "activity name",
    "reference_product": "reference product",
    "location": "GLO",
    "categories": [],
    "unit": "kilogram",
    "type": "process",
    "key": ["bafu", "activity-code"]
  }
]
```

Preserve both elements of `key`. They are stable identifiers for activity
lookup. Do not substitute a guessed name when a later endpoint requests
`database` and `code`.

### Get direct activity inputs

```http
POST /api/database/activity-inputs
Content-Type: application/json
```

Request:

```json
{
  "database": "bafu",
  "code": "activity-code",
  "exchange_type": "technosphere",
  "limit": 100
}
```

Required fields are `database` and `code`. Get them from a search result's
`key`. Optional `exchange_type` values are `technosphere`, `biosphere`, or
`production`; omit it to return all direct exchanges. The default limit is 500.

Response: a JSON array whose objects include fields such as:

```json
{
  "input_database": "bafu",
  "input_code": "input-code",
  "input_name": "input activity or flow",
  "input_product": "reference product",
  "input_location": "GLO",
  "exchange_type": "technosphere",
  "amount": 1.25,
  "unit": "kilogram",
  "uncertainty_type": 0,
  "loc": null,
  "scale": null,
  "minimum": null,
  "maximum": null
}
```

Amounts are direct inventory quantities, not impact scores or contribution
percentages.

### Discover the SQL schema

```http
GET /api/database/schema
```

Call this immediately before writing SQL. Its `schema_objects` field contains
the live public DDL. Its `query_contract` describes limits and restrictions,
and its `semantics` explains exchange direction.

The supported public surfaces are:

- `activities`
- `exchanges`
- `exchange_details`
- `activities_fts`

Prefer `exchange_details` when readable activity and flow names are needed.
In this view, `output_*` identifies the consuming activity and `input_*`
identifies the supplied activity or biosphere flow.

### Run read-only SQL

```http
POST /api/database/query
Content-Type: application/json
```

Request:

```json
{
  "sql": "SELECT name, location FROM activities WHERE database='bafu' AND name LIKE '%cotton%'",
  "limit": 100
}
```

Only one `SELECT` or `WITH ... SELECT` statement is permitted. Mutations,
multiple statements, `PRAGMA`, `ATTACH`, and extension loading are denied.
The default limit is 100, the valid range is 1–10,000, and queries have a
three-second execution limit.

Response:

```json
{
  "columns": ["name", "location"],
  "rows": [["activity name", "GLO"]],
  "count": 1,
  "truncated": false,
  "fresh": true,
  "built_at": "timestamp",
  "source_databases": ["bafu", "biosphere3", "mock_background"]
}
```

Never issue destructive SQL, even if a user asks for it. This endpoint is a
read-only projection, not Brightway's internal database.

### List and retrieve case studies

```http
GET /api/case-studies
GET /api/case-studies/mock_plastic_broom
```

The list endpoint returns names:

```json
["cotton_fiber", "jacket", "mock_plastic_broom", "mock_storage_bin", "polyester_tshirt", "wool_yarn"]
```

The detail endpoint returns a bundle containing:

```json
{
  "product_graph": "YAML document as a string",
  "svg_structure": "<svg ...>",
  "svg_scaled": "<svg ...>",
  "unit_process_svgs": {
    "exact process name": "<svg ...>"
  }
}
```

Use case studies to obtain known-valid product graph YAML and exact foreground
process names. The two `mock_*` examples use the bundled fictional
`mock_background` database and are appropriate for deterministic client tests.

### Run an LCA

```http
POST /api/lca/run
Content-Type: application/json
```

Request:

```json
{
  "product_graph": "name: Example\nfunctional_unit:\n  amount: 1.0\n  unit: kg\n..."
}
```

`product_graph` is required and must be one YAML document encoded as a JSON
string. Do not convert the YAML into a nested JSON object. The easiest safe
workflow is to retrieve `product_graph` from a case study and pass that string
unchanged.

Response fields include:

```json
{
  "name": "analysis name",
  "method": "LCIA method family",
  "functional_unit": "1.0 kg — description",
  "lci": {},
  "lcia": {
    "impact category": {
      "score": 1.23,
      "unit": "kg CO2-Eq"
    }
  },
  "scaling_vector": {},
  "result_schema_version": 2,
  "process_contributions": {
    "categories": []
  },
  "sankey": {
    "nodes": [],
    "links": [],
    "available_units": []
  },
  "svg_scaled": "<svg ...>",
  "svg_structure": "<svg ...>"
}
```

Report impact values with their returned units. Never infer or replace units.

The operation is stateless: `product_graph` is the complete input, and no
session or result identifier is required. `process_contributions.categories`
contains one entry per `lcia` category. Its exclusive foreground process scores
plus `residual_score` reproduce the category total; background activity impact
is aggregated into the residual. A null percentage means the category total is
effectively zero. Negative scores and percentages are valid and must not be
clamped.

`sankey.links` contains scaled technosphere, extraction, emission, and
final-product quantities. Every endpoint references an entry in
`sankey.nodes`. Use `available_units` to select compatible links before mapping
amounts to widths; never combine incompatible units into one width scale.

### Render a product graph

```http
POST /api/lca/svg
Content-Type: application/json
```

Request:

```json
{
  "product_graph": "YAML document as a string",
  "graph_type": "scaled"
}
```

`graph_type` defaults to `scaled`; the other supported value is `structure`.

Response:

```json
{"svg": "<svg ...>"}
```

Treat the SVG string as an opaque image asset unless the user explicitly asks
for SVG source analysis.

### Render one foreground unit process

```http
POST /api/lca/svg/unit-process
Content-Type: application/json
```

Request:

```json
{
  "product_graph": "YAML document as a string",
  "process_name": "P2 — Cotton farming"
}
```

`process_name` must exactly match a process name in the product graph. The
response is `{"svg":"<svg ...>"}`.

### Render a BAFU background supply chain

```http
POST /api/lca/svg/bafu
Content-Type: application/json
```

Request:

```json
{
  "activity_name": "exact BAFU process name",
  "location": "GLO",
  "method_name": "EF v3.1",
  "method_category": "climate change",
  "max_depth": 4,
  "cutoff": 0.01,
  "database": "bafu"
}
```

Only `activity_name` and `location` are required. Defaults are shown above.
Get an exact process name and location from `POST /api/database/search` instead
of guessing. The response is `{"svg":"<svg ...>"}`.

## Recommended multi-call workflows

### Analyze a bundled example

1. `GET /api/case-studies`
2. Choose a returned name.
3. `GET /api/case-studies/{name}`
4. Extract the `product_graph` string.
5. `POST /api/lca/run` with that string.
6. Present `lcia` scores with their units; show returned SVGs only if useful.

### Explore a background process

1. `POST /api/database/search` with `database="bafu"`.
2. Ask the user to choose if several results are plausible.
3. Preserve the selected result's `key`, exact `name`, and `location`.
4. Use the key with `POST /api/database/activity-inputs`.
5. Optionally use the exact name/location with `POST /api/lca/svg/bafu`.

### Answer an inventory database question

1. `GET /api/database/schema`.
2. Prefer typed search/input endpoints if possible.
3. Otherwise construct one read-only SQL query against the documented schema.
4. Call `POST /api/database/query`.
5. If `truncated` is true, refine the query before increasing the limit.

## Error handling

- `200`: parse the JSON body. For health, also inspect the `running` field.
- `400`: the request is invalid or the calculation/query failed. Read `detail`,
  correct the arguments, and retry only after making a meaningful change.
- `404`: a case-study name or route was not found. Refresh discovery/list data.
- `503`: the service is unavailable or restarting. Retry later with bounded
  exponential backoff.
- Network timeout: calculations and graph traversal can take longer than simple
  list/search calls. Do not assume failure produced a valid result.

Never fabricate a successful calculation, method, activity key, process name,
or unit after an API error. Explain the error or request the missing choice.

## Minimal agent instructions

The following text can be placed in an LLM's system or tool-use prompt:

```text
Use https://lca-mcp.mathplosion.com as the origin for LCA REST requests. First
call GET /api/health and require running=true. Then call GET /api/tools
and use each operation's input_schema and rest method/path. Send JSON for POST
requests. product_graph is YAML encoded as one JSON string, not a nested JSON
object. Search before selecting BAFU activities; preserve the returned database
and code key. Call /api/database/schema before writing one read-only SQL query.
Treat exchange amounts as inventory quantities, not impact scores. Report LCIA
scores with their returned units. Never invent missing activities, method names,
process names, results, or units. On HTTP 400 read detail and correct the call;
on 503 retry later with bounded backoff.
```
