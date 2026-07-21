# Tiny Mock Background Database

The repository includes a three-process background database named
`mock_background`. It is deliberately small, deterministic, and fictional. It
exists for teaching, UI development, and REST/MCP integration testing without
depending on a large real-world database.

## Activities

| Code | Activity | Unit | Direct inputs |
|---|---|---|---|
| `mock-grid-electricity` | Mock grid electricity, medium voltage | kilowatt hour | CO2 and SO2 emissions |
| `mock-polypropylene` | Mock polypropylene granulate, at plant | kilogram | Mock grid electricity, CO2, SO2 |
| `mock-small-truck` | Mock freight transport, small truck | ton kilometer | Mock grid electricity, CO2, SO2 |

The version-controlled source of truth is
[`mock_background/database.yaml`](../mock_background/database.yaml). Never use
these invented inventories for environmental claims or comparisons with
openLCA datasets.

The companion `lca-mock-tests` repository contains the equivalent
`mock_plastic_broom` graph as expanded openLCA JSON-LD, a generated import ZIP,
and hand-calculated expected results. That independent representation allows
the same inventories and scaling to be checked in both Brightway and openLCA.

## Installation and startup

The server installs or refreshes this generated database during normal startup,
after `biosphere3` is ready. It is shared read-only reference data; REST
requests still create isolated temporary foreground databases and delete them
after each calculation. No request can mutate `mock_background`.

To install it explicitly in the configured Brightway project:

```bash
uv run python scripts/install_mock_database.py
```

The installer is idempotent. It hashes the YAML source and only replaces the
generated database when that source changes. The search projection includes
the mock database, so it is available through `/api/databases`,
`/api/database/search`, `/api/database/activity-inputs`, and read-only SQL.

## Internal test product graphs

- `mock_examples/mock_storage_bin.yaml` references one background process.
- `mock_examples/mock_plastic_broom.yaml` references two background processes.

Their expected EF v3.1 climate-change scores are 1.440000 and 0.948871 kg
CO2-Eq, respectively.

These fixtures are packaged for tests but intentionally excluded from
`GET /api/case-studies`. Run the local broom fixture against an API:

```bash
BASE_URL=http://localhost:9000

jq -Rs '{product_graph: .}' mock_examples/mock_plastic_broom.yaml \
  | curl -s -X POST "$BASE_URL/api/lca/run" \
      -H 'Content-Type: application/json' \
      --data-binary @- \
  | jq '{name, lcia, scaling_vector, sankey}'
```

Search the tiny database directly:

```bash
curl -s -X POST "$BASE_URL/api/database/search" \
  -H 'Content-Type: application/json' \
  -d '{"query":"mock", "database":"mock_background", "limit":10}' | jq
```
