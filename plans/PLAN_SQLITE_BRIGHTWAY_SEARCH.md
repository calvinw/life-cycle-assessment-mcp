# Plan: A Searchable SQLite Projection of Brightway Data

## Decision

Build a **separate, disposable SQLite database for search and exploration**.
Do not replace, subclass, or modify Brightway's storage backend. Do not make
`bw2calc` or `run_lca` depend on the search database.

Brightway remains the authoritative source for imports, activity resolution,
and all LCA calculations. A builder reads activities and exchanges through
Brightway's public Python API and writes their useful fields into ordinary
SQLite columns. No pickle values are copied into the search database.

This is a material simplification of the earlier DoltLite proposal:

- no custom Brightway backend;
- no DoltLite dependency;
- no branches or version-control semantics;
- no changes to background importers for v1;
- no risk that calculation code accidentally reads the projection.

The projection can always be deleted and rebuilt from Brightway.

---

## Problem being solved

Brightway's `databases.db` already exposes activity identity fields such as
`name`, `product`, and `location`, plus exchange endpoints and types. Most
other activity and exchange data is stored in a pickled `data` BLOB. In
particular, SQL cannot directly filter, sort, aggregate, or compare exchange
`amount`, `unit`, uncertainty, categories, comments, or classifications.

This repository currently exposes that limitation through
`query_lca_database()`: callers can query process identity and graph links,
but not quantities or most descriptive metadata.

The new database should support questions such as:

- Which processes produce a material matching a phrase, and in which regions?
- What technosphere inputs does a process consume, in what amounts and units?
- Which processes consume a given activity or biosphere flow?
- How do otherwise similar candidate processes differ in their direct inputs?
- Which activities mention a term in their name, product, comment,
  classifications, or categories?

It is a discovery tool, not a calculation engine. An exchange amount is a
direct inventory relationship; it is not an LCIA result and must not be
presented as one.

---

## Architecture and data flow

```text
Source import (BAfU, USLCI, ecoinvent, etc.)
                  |
                  v
        Brightway SQLite backend
        - authoritative data
        - used by run_lca/bw2calc
                  |
                  | public bw2data objects
                  | Database -> Activity -> Exchange
                  v
        search.sqlite3 [new projection]
        - normalized scalar columns
        - JSON text only for uncommon variable-shape metadata
        - FTS5 text index
        - opened read-only by MCP query tools
```

The first version is built **after** a Brightway import, rather than modifying
each importer to write two destinations. This adds a rebuild step, but keeps
the implementation generic and decoupled from every source format.

### Invariants

1. Brightway is the only source of truth.
2. `run_lca` and `bw2calc` never read `search.sqlite3`.
3. The projection contains no Python pickle or other opaque binary payload.
4. Search tools never mutate Brightway or the projection.
5. A failed rebuild cannot damage the last complete projection.
6. Search results identify activities by `(database, code)`, which is the key
   callers pass back to Brightway for authoritative lookup and calculation.

---

## Proposed SQLite schema (v1)

Use a schema version recorded in `projection_metadata`. Schema migrations are
not required initially: when the version changes, rebuild the disposable file.

### `projection_metadata`

One row per property:

| column | type | purpose |
|---|---|---|
| `key` | TEXT PRIMARY KEY | Metadata name |
| `value` | TEXT NOT NULL | JSON-encoded or scalar value |

Required keys:

- `schema_version`
- `built_at` (UTC ISO 8601)
- `brightway_project`
- `bw2data_version`
- `source_databases` (JSON array)
- `source_fingerprint` (JSON object; see freshness below)
- `activity_count`
- `exchange_count`

### `activities`

One row per Brightway node, including process nodes and biosphere flows:

| column | type | notes |
|---|---|---|
| `database` | TEXT NOT NULL | Part 1 of the Brightway key |
| `code` | TEXT NOT NULL | Part 2 of the Brightway key |
| `brightway_id` | INTEGER | Brightway internal numeric id, informational only |
| `name` | TEXT NOT NULL | Activity or flow name |
| `reference_product` | TEXT | Brightway `reference product`/`product` |
| `location` | TEXT | Geographic code |
| `unit` | TEXT | Reference unit |
| `type` | TEXT | Process, product, emission, etc. |
| `categories_text` | TEXT | `::`-joined categories for simple display/search |
| `comment` | TEXT | Source description/comment |
| `filename` | TEXT | Source filename when available |
| `extra_json` | TEXT NOT NULL DEFAULT `'{}'` | Valid JSON for unmodeled fields |

Primary key: `(database, code)`.

`extra_json` preserves uncommon source metadata without pickling it. Fields
that become important for filtering should later be promoted to typed columns;
the JSON field is not a substitute for modeling known core fields.

### `activity_categories`

Preserve ordered category paths without requiring JSON parsing:

| column | type |
|---|---|
| `database` | TEXT NOT NULL |
| `code` | TEXT NOT NULL |
| `position` | INTEGER NOT NULL |
| `category` | TEXT NOT NULL |

Primary key: `(database, code, position)`. Foreign key to `activities`.

### `activity_classifications`

| column | type |
|---|---|
| `database` | TEXT NOT NULL |
| `code` | TEXT NOT NULL |
| `system` | TEXT NOT NULL |
| `value` | TEXT NOT NULL |

Foreign key to `activities`. Index `(system, value)`.

### `activity_synonyms`

| column | type |
|---|---|
| `database` | TEXT NOT NULL |
| `code` | TEXT NOT NULL |
| `synonym` | TEXT NOT NULL |

Foreign key to `activities`. Index `synonym COLLATE NOCASE`.

### `exchanges`

One row per directed exchange. `output_*` is the consuming/target activity;
`input_*` is the supplied/source activity or biosphere flow.

| column | type | notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Projection-local id |
| `brightway_id` | INTEGER | Source exchange id when exposed |
| `output_database` | TEXT NOT NULL | Consuming activity database |
| `output_code` | TEXT NOT NULL | Consuming activity code |
| `input_database` | TEXT NOT NULL | Input activity/flow database |
| `input_code` | TEXT NOT NULL | Input activity/flow code |
| `type` | TEXT NOT NULL | `technosphere`, `biosphere`, `production`, etc. |
| `amount` | REAL NOT NULL | Numeric exchange amount |
| `unit` | TEXT | Unit recorded on the exchange |
| `name` | TEXT | Exchange/source name as imported |
| `reference_product` | TEXT | Exchange/source reference product |
| `location` | TEXT | Exchange/source location |
| `categories_text` | TEXT | `::`-joined categories |
| `uncertainty_type` | INTEGER | Brightway uncertainty type id |
| `loc` | REAL | Distribution location parameter |
| `scale` | REAL | Distribution scale parameter |
| `shape` | REAL | Distribution shape parameter |
| `minimum` | REAL | Distribution lower bound |
| `maximum` | REAL | Distribution upper bound |
| `negative` | INTEGER | Boolean encoded as 0/1 |
| `formula` | TEXT | Parameterized amount formula, if present |
| `extra_json` | TEXT NOT NULL DEFAULT `'{}'` | Valid JSON for other non-core fields |

Foreign key:

- `(output_database, output_code)` -> `activities(database, code)`

The builder should include dependencies (for example `biosphere3` when
building `bafu`) by default so input keys can resolve to activity metadata.
Do not declare a strict input-endpoint foreign key in v1. If a source genuinely
references an omitted database, retain the exchange rather than dropping the
row. Validate input references after loading, report unresolved keys, and
expect all of them to resolve when declared dependencies were included.

Indexes:

- `(output_database, output_code, type)` for listing a process's inputs;
- `(input_database, input_code, type)` for reverse dependency search;
- `(type, unit)` for inventory filtering;
- `name COLLATE NOCASE`;
- `amount` only if measured queries show it is useful (do not add it by habit).

### `activities_fts`

An FTS5 virtual table for discovery over:

- `name`
- `reference_product`
- `comment`
- flattened categories
- flattened classifications
- flattened synonyms

Store `database` and `code` as unindexed columns so matches join back to the
canonical row. Because the projection is rebuilt as a unit, populate FTS once
at build time; triggers are unnecessary in v1.

If the runtime SQLite lacks FTS5, fail the build with a clear diagnostic. Do
not silently produce a database whose advertised search behavior is missing.

### Convenience views

Create `exchange_details`, joining each exchange to both endpoint activities.
Expose readable aliases such as:

- `consumer_name`, `consumer_product`, `consumer_location`
- `input_name`, `input_product`, `input_location`
- `amount`, `unit`, `exchange_type`

This view prevents callers from repeatedly writing error-prone endpoint joins.
Create `process_inputs` as a filtered view excluding production exchanges if
that proves useful in MCP prompts.

---

## Extraction and build behavior

Add a module such as `search_database.py` and a CLI entry point such as:

```bash
uv run python scripts/build_search_database.py --database bafu
```

Default behavior:

1. Select the configured Brightway project.
2. Verify every requested database exists.
3. Expand the selection to its declared dependencies unless
   `--no-dependencies` is explicitly passed.
4. Read each node with `bw2data.Database(name)`.
5. Read each outgoing exchange with `activity.exchanges()`.
6. Convert known fields to typed SQLite values.
7. Convert tuples, sets, and other extra metadata to deterministic JSON-safe
   structures; reject values that cannot be serialized rather than stringifying
   them ambiguously.
8. Insert in batches inside a transaction.
9. Populate normalized metadata tables and FTS.
10. Run validation queries and `PRAGMA integrity_check`.
11. Write metadata and commit.
12. Atomically replace the previous complete projection.

Use the Brightway object API rather than directly unpickling the source `data`
column. This keeps ownership of Brightway's serialization format inside
Brightway and gives the projection builder ordinary Python dictionaries.

For the current local data, size the implementation for at least 12,000 BAfU
activities and 412,000 exchanges. Use `executemany` batches and avoid building
one giant list or DataFrame in memory. Log per-database counts and elapsed time.

### Output location

Default to a deterministic file inside the active Brightway project directory,
for example:

```text
<brightway project directory>/search/search.sqlite3
```

Allow `--output` for tests and offline artifacts. The MCP layer should obtain
the path from one shared helper; it must not repeat the existing glob-based
path discovery.

### Atomic rebuild

Build `search.sqlite3.tmp-<pid>` in the same directory, close it, validate it,
then replace `search.sqlite3` with `os.replace`. A failed build removes only its
temporary file and leaves the previous projection usable.

The builder should use an advisory lock file to prevent simultaneous rebuilds.
Queries open the completed file read-only and can continue using the previous
inode during replacement.

---

## Freshness and rebuild policy

The projection is a snapshot, so staleness must be visible.

Create a source fingerprint from each included Brightway database's:

- name;
- `number`;
- `modified` metadata value;
- backend name;
- declared dependencies.

At query time compare the stored fingerprint with current Brightway metadata.
Return freshness information alongside query results:

```json
{
  "fresh": true,
  "built_at": "...",
  "source_databases": ["bafu", "biosphere3"]
}
```

If stale, refuse by default with instructions to rebuild. An explicit internal
override can permit stale reads for diagnosis, but should not be exposed as the
normal MCP behavior.

For v1, rebuild explicitly after imports and when freshness checks fail. Do not
add filesystem watchers, signals, dual writes, or incremental synchronization.

---

## Query API and safety

Replace the current raw-Brightway SQL tools with projection-aware equivalents,
while retaining old function names only if compatibility requires it:

1. `get_lca_search_schema()` returns actual tables, columns, views, example
   queries, schema version, source databases, and freshness.
2. `query_lca_search_database(sql, params=None, limit=100)` runs a read-only
   query against `search.sqlite3`.
3. `search_lca_activities(text, database=None, location=None, limit=25)` offers
   a structured FTS-based path for the common case.
4. `get_lca_activity_inputs(database, code, exchange_type=None, limit=...)`
   returns typed rows from `exchange_details` without requiring generated SQL.

Raw query rules:

- open SQLite with URI `mode=ro`;
- set `PRAGMA query_only = ON`;
- accept exactly one statement;
- allow `SELECT` and `WITH ... SELECT`, not just strings beginning with
  `SELECT`;
- reject mutation, attachment, writable pragmas, extension loading, and
  transaction control using SQLite's authorizer callback;
- enforce both a row cap and an execution-time/VM-step budget;
- bind user values as parameters in structured tools;
- return `truncated: true` when more rows exist than the response cap.

The current prefix-only `SELECT` check is insufficient as a security boundary
and prevents useful CTEs. The read-only connection and SQLite authorizer should
be the boundary.

---

## Example queries

Find likely material-producing processes:

```sql
SELECT a.database, a.code, a.name, a.reference_product, a.location, a.unit
FROM activities_fts AS f
JOIN activities AS a
  ON a.database = f.database AND a.code = f.code
WHERE activities_fts MATCH 'polylactide'
ORDER BY rank
LIMIT 25;
```

List the direct technosphere inputs to one process:

```sql
SELECT input_name, input_product, input_location, amount, unit
FROM exchange_details
WHERE output_database = ?
  AND output_code = ?
  AND exchange_type = 'technosphere'
ORDER BY ABS(amount) DESC;
```

Find processes consuming a given background activity:

```sql
SELECT consumer_name, consumer_location, amount, unit
FROM exchange_details
WHERE input_database = ? AND input_code = ?
ORDER BY consumer_name;
```

These amounts are not generally comparable across arbitrary processes unless
their reference products and units are compatible. Search tooling and prompts
must preserve that caveat.

---

## Implementation phases

### Phase 1: projection builder

- Implement schema creation and schema version metadata.
- Extract `bafu` plus `biosphere3` through the public Brightway API.
- Populate all typed fields, JSON extras, indexes, FTS, and views.
- Add count, reference, JSON-validity, and integrity validation.
- Add the atomic CLI rebuild workflow.

### Phase 2: query integration

- Add a shared projection-path and freshness helper.
- Point schema/raw query MCP tools at the projection.
- Add structured activity search and activity-input tools.
- Update tool descriptions so an LLM understands endpoint direction,
  quantities, units, and the difference between inventory and LCIA.

### Phase 3: genericity and performance

- Test the same builder on a second Brightway-compatible background database.
- Benchmark build time, database size, FTS latency, and common graph joins.
- Promote frequently queried `extra_json` fields into typed columns based on
  evidence from real searches.

Incremental refresh remains deferred until full rebuild performance proves it
is necessary.

---

## Acceptance criteria

### Data correctness

- Projection activity count equals the sum of selected Brightway databases.
- Projection exchange count equals all exchanges emitted by selected
  activities.
- For a deterministic sample of at least 100 exchanges across each type,
  endpoint keys, amount, unit, and uncertainty fields equal Brightway values.
- Every `extra_json` value passes `json_valid`.
- Every exchange output key resolves to an activity.
- Unresolved input keys are counted and reported; none are silently dropped.
- `PRAGMA integrity_check` returns `ok`.
- Application-owned tables declare no BLOB columns and contain no copied
  pickle payloads. (SQLite's internal FTS5 shadow tables are outside this
  requirement.)

### Search behavior

- FTS finds terms present only in names, reference products, comments,
  categories, classifications, and synonyms.
- A direct-input query returns correct numeric amounts and units without Python
  deserialization at query time.
- Reverse dependency lookup works using `(input_database, input_code)`.
- Structured search results always include the Brightway `(database, code)`
  key.

### Isolation and reliability

- Deleting `search.sqlite3` does not affect `run_lca`.
- Corrupting or interrupting a temporary rebuild leaves the previous complete
  projection usable.
- Modifying/reimporting a Brightway database causes freshness validation to
  fail until rebuilding.
- Query connections cannot modify either SQLite database.
- Existing representative LCIA scores are unchanged before and after building
  the projection.

### Performance targets

Record benchmarks before setting hard production thresholds. As an initial
local target for the current BAfU dataset:

- full build completes in under two minutes;
- common FTS searches return in under 250 ms;
- indexed direct-input and reverse-dependency queries return in under 100 ms.

Treat these as measurement targets, not correctness requirements.

---

## Explicitly deferred

- Replacing or extending Brightway's backend.
- Making `bw2calc` consume the projection.
- DoltLite, branching, merging, and scenario version control.
- Import-time dual writes or hooks into individual source importers.
- Incremental synchronization and change-data capture.
- Editing the background database through search tools.
- Computing LCIA values inside SQLite.
- Searching multiple independently built projections in one query.

---

## Decisions still to make during implementation

1. Whether the initial MCP release replaces `query_lca_database()` in place or
   adds new tool names for a compatibility period.
2. Which uncommon source fields deserve first-class columns after examining a
   second background database.
3. Whether comments should be included in FTS by default if index size becomes
   disproportionate.
4. Whether redistribution needs a prebuilt projection artifact, or whether it
   should always be generated locally after the Brightway tarball is installed.
