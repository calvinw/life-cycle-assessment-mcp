# LCA database types and lifecycle

This guide explains the data stores used by the LCA engine, when each one is
created, what it contains, and how a product graph moves through them.

The most important distinction is that a product graph does **not** get its own
persistent searchable SQLite database. A request creates a temporary Brightway
foreground database, combines it with shared background data for the
calculation, and deletes it afterward. The searchable SQLite database is a
separate, persistent projection of the shared background inventory.

## System overview

```text
Version-controlled inputs                 Brightway project
-------------------------                 -----------------
BAFU release archive -------------------> bafu background database ----+
biosphere data --------------------------> biosphere3 flows ------------+-- LCA
mock_background/database.yaml ----------> mock_background database ----+   calculation
                                                                         |
Product graph YAML -- per request ------> foreground_request_<uuid> ----+
                                            temporary; always deleted

Shared background databases ------------> search/search.sqlite3
                                            persistent, disposable,
                                            read-only projection used
                                            for discovery and inspection

Shared background databases + methods --> in-process intensity cache
                                            memory only; rebuilt when the
                                            server process starts
```

## Database and storage types

| Store | Scope | Lifetime | Source of truth? | Used in calculation? |
| --- | --- | --- | --- | --- |
| Brightway project store | One configured project | Persistent | Yes | Yes |
| `bafu` | Shared background database | Persistent | Yes | Yes |
| `biosphere3` | Shared elementary-flow database | Persistent | Yes | Yes |
| `mock_background` | Shared teaching database | Persistent but reproducible | Yes for mock examples | Yes |
| `foreground_request_<uuid>` | One product-graph request | Temporary | No; YAML is authoritative | Yes |
| `search/search.sqlite3` | One Brightway project | Persistent but disposable | No | No |
| Background intensity cache | One Python process | Memory only | No | Used to accelerate contribution results |

### Brightway project store

The configured project defaults to `lca_server`. Brightway owns its on-disk
layout under `BRIGHTWAY2_DIR`; in a local checkout the default root is
`brightway_data/`. The project contains activity and exchange records,
database metadata, processed matrices, and LCIA method data.

Files such as `databases.db`, `databases.json`, `methods.json`, and the
`processed/` and `intermediate/` directories are Brightway implementation
details. Application code should use the Brightway API instead of querying or
editing these files directly.

### Shared background databases

`bafu` contains the production background inventory. `mock_background`
contains a tiny fictional inventory used by examples and tests. Their
dependencies, including `biosphere3`, are resolved by Brightway.

A background activity is a process or flow record. Its exchanges describe:

- production: the activity's reference output;
- technosphere: products and services supplied by other activities; and
- biosphere: elementary resource inputs and environmental emissions.

These databases are shared across requests. Product-graph calculations read
them but do not add request-specific foreground activities to them.

### Temporary foreground database

Every calculation creates a database named
`foreground_request_<random UUID>`. It contains one Brightway activity for
each entry in `product_graph.processes`.

For each process, the engine writes:

- one production exchange from `reference_output`;
- a technosphere exchange for each item in `inputs`;
- a biosphere exchange for each item in `emissions`; and
- a biosphere exchange for each item in `resources`.

An input without a `database` field links to the foreground activity that
provides the named product flow. An input with a `database` field links to an
installed background activity, preferably by exact `code`, or otherwise by
exact name and optional location.

The product graph YAML remains the complete, authoritative request. The
temporary foreground database exists only so Brightway can assemble and solve
the combined foreground/background matrices. A `finally` block deletes it
after success or failure, so it is normally too short-lived to inspect from a
separate process.

### Searchable SQLite projection

The searchable database is stored at:

```text
<Brightway project directory>/search/search.sqlite3
```

It is a denormalized projection built from `bafu`, `mock_background`, and their
dependencies. It supports fast discovery and safe SQL access, but Brightway
remains authoritative and never reads this projection to perform an LCA.

Public tables:

- `projection_metadata`: schema version, build time, project, source database
  fingerprint, and row counts;
- `activities`: process and flow identity, name, product, location, unit, type,
  comments, and extra metadata;
- `activity_categories`: ordered activity categories;
- `activity_classifications`: classification system/value pairs;
- `activity_synonyms`: searchable alternative names;
- `exchanges`: direct production, technosphere, and biosphere exchanges,
  including amounts, endpoints, units, and uncertainty fields; and
- `activities_fts`: an FTS5 index over names, products, comments, categories,
  classifications, and synonyms.

Public views:

- `exchange_details`: exchanges joined to readable consumer and input
  activity metadata; and
- `process_inputs`: all non-production rows from `exchange_details`.

Request-specific `foreground_request_<uuid>` databases are not included.

### In-process background intensity cache

This is not a database file. It holds background LCA objects, matrix
factorizations, and cumulative LCIA intensity vectors in Python memory. It is
warmed during engine readiness for configured database/method combinations and
is reused across requests in the same server process. It is rebuilt after a
restart and invalidated when the identity of its source background databases
changes.

## Startup and readiness stages

The first `engine.ensure_ready()` call, or the first calculation/query that
requires readiness, performs these stages:

1. Select the configured Brightway project.
2. Ensure `bafu` exists. On a fresh installation, download and extract the
   configured release archive, then reload project metadata.
3. Remove the obsolete persistent database named `foreground`, if present.
4. Install or refresh `mock_background` when its version-controlled YAML hash
   has changed.
5. Check the searchable projection's freshness.
6. Rebuild `search.sqlite3` if it is missing, unreadable, on an old schema,
   tied to another project, missing expected sources, or based on changed
   Brightway database metadata.
7. Warm the in-memory background intensity cache.

The readiness operation is guarded so these checks run once per engine process
after successful initialization.

## Search projection build stages

When rebuilding `search.sqlite3`, the engine:

1. Expands the selected source databases to include their declared
   dependencies.
2. Takes an exclusive build lock.
3. Creates a uniquely named temporary SQLite file beside the destination.
4. Creates the public tables, indexes, FTS5 table, and views.
5. Copies activities and exchanges from each selected Brightway database.
6. Writes projection metadata and a source fingerprint based on each
   database's activity count, modification timestamp, backend, and
   dependencies.
7. Validates row counts, FTS coverage, endpoint resolution, and SQLite
   integrity.
8. Atomically replaces the old `search.sqlite3` with the validated temporary
   file.

The old projection remains available until the replacement is complete. A
failed build removes its temporary file and does not publish a partial
database.

## Product-graph calculation stages

`run_lca` and `run_lca_base` follow this lifecycle:

1. **Parse YAML.** Load the complete product-graph document.
2. **Validate the model.** Check process and product identities, finite
   amounts, units, reference process, LCIA method, and requested categories.
3. **Ensure readiness.** Make the shared databases, search projection, and
   caches available as described above.
4. **Create isolated foreground data.** Build a uniquely named temporary
   foreground database and resolve all foreground, background, and biosphere
   links.
5. **Assemble the demand.** Demand the functional-unit amount from the
   configured reference process.
6. **Build and solve the inventory.** Brightway combines the temporary
   foreground activities with all reachable background activities, builds the
   technosphere and biosphere matrices, and solves the supply array.
7. **Calculate impacts.** Apply each requested LCIA method/category to the
   inventory.
8. **Build response data.** Produce inventory totals, LCIA totals, the
   foreground scaling vector, direct process contributions, background-link
   intensities, and Sankey data. Full runs can also include cumulative
   contribution graphs.
9. **Validate the result.** Reject non-finite values before returning.
10. **Delete foreground data.** Remove the request database in cleanup,
    whether calculation succeeded or failed.

`run_lca_base` omits cumulative contribution graphs. A later
`get_lca_contribution_graphs` request validates the deterministic `result_id`
and independently rebuilds the same temporary foreground model from the same
YAML; no server-side product-graph session is retained.

## What can be inspected with MCP tools

- `list_databases` lists installed Brightway databases and dependencies.
- `list_impact_methods` lists available LCIA methods and categories.
- `get_lca_database_schema` returns the live public schema, metadata, and query
  contract for `search.sqlite3`.
- `search_database` searches projected activities and flows.
- `query_lca_database` runs one read-only `SELECT` or CTE against the
  projection.
- `get_lca_activity_inputs` returns one projected activity's direct exchanges.
- `run_lca_base` and `run_lca` expose calculated results, not the temporary
  foreground database itself.

For example, inspect projection metadata with:

```sql
SELECT key, value
FROM projection_metadata
ORDER BY key
```

Inspect counts by source database with:

```sql
SELECT database, COUNT(*) AS activities
FROM activities
GROUP BY database
ORDER BY database
```

Inspect the direct recipe for an exact activity with:

```sql
SELECT exchange_type, input_name, input_location, amount, unit
FROM exchange_details
WHERE output_database = 'bafu' AND output_code = '<activity code>'
ORDER BY exchange_type, input_name
```

## Operational implications

- Search results describe shared background inventory, not a submitted
  product graph.
- Changing a product graph does not require rebuilding `search.sqlite3`.
- Changing a projected Brightway source database makes the projection stale;
  the next readiness check rebuilds it.
- Deleting `search.sqlite3` does not delete authoritative inventory data; the
  projection can be rebuilt.
- Directly editing Brightway's internal SQLite files or the search projection
  is unsupported.
- To retain a product graph, store its YAML or a returned result externally;
  the server deliberately does not retain request state.

## Related documentation

- [Searching the LCA Background Database](searchable_background_database.md)
- [Python engine and MCP separation](python_engine.md)
- [Tiny Mock Background Database](mock_background_database.md)
- [Setting up the BAFU Database](setup_bafu_database.md)
- [REST API](rest_api.md)
