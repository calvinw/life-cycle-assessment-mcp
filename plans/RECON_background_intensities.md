# Reconnaissance: Precomputed Background Cumulative Intensities

Status: Phase 0 reviewed and accepted  
Date: August 17, 2026  
Branch: `plan/background-intensity-feasibility`  
Baseline commit: `aade58d` (`origin/main` at reconnaissance start)

## Executive finding

Tier 1 is technically feasible in this codebase, and the production adjoint path
already exists. The implementation can therefore be differential and narrow: it
can compare a precomputed background product-intensity vector with the existing
per-request full adjoint before changing which result is used.

Four parts of the implementation brief must be resolved before the experimental
phases are run:

1. The intended BAFU T-shirt fixture exists at
   `bafu_examples/polyester_tshirt_bafu.yaml`, not
   `case_studies/polyester_tshirt.yaml`. It fixes the empty-background problem,
   but it and the BAFU broom both have one foreground process, contrary to the
   brief's statement that their process counts differ.
2. The tracked files in `case_studies/` are foreground-only. Requiring
   `A_BF.nnz > 0` for every case study is therefore impossible by construction.
3. The two-call pipeline deliberately calls `lca.lci()`, not
   `lca.lci(factorize=True)`. Its forward factorization is not retained; the
   separately-created transpose factorization is the item Tier 1 can remove from
   request time.
4. `mock_background` has a source checksum and schema version, but the installed
   `bafu` metadata has no durable source version or checksum. Phase 3 must not key
   the cache on the BAFU name alone.

These are planning corrections, not evidence against the mathematical claim.

## 1. Foreground construction and lifecycle

The temporary foreground database is created through
`_request_foreground()` in `lca_core/engine.py:632-655`.

- Its name is `foreground_request_` plus `uuid.uuid4().hex`
  (`lca_core/engine.py:43-44`, `lca_core/engine.py:640`). This gives each request
  an independently generated 128-bit UUID name.
- `_build_foreground_db()` registers the database and creates one activity for
  each YAML process (`lca_core/engine.py:515-538`). It then writes production,
  technosphere, and biosphere exchanges (`lca_core/engine.py:540-627`).
- The whole context is protected by `_calculation_lock`, and cleanup is in a
  `finally` block (`lca_core/engine.py:641-655`). Cleanup deletes the uniquely
  named database from `bd.databases` if it still exists.
- The full/base path enters this context at `lca_core/engine.py:961-970`; the lazy
  contribution path enters it at `lca_core/engine.py:1222-1227`.

Conclusion: Invariant B1 is structurally plausible. Foreground exchanges can
point to background providers, but background activities are not edited by this
construction path.

## 2. LCA construction and the forward solve

The relevant `bc.LCA(...)` instantiations are:

- full/base calculation: `lca_core/engine.py:1000-1005`;
- lazy Call 2 contribution calculation: `lca_core/engine.py:1259-1265`.

Both call `lca.lci()` without `factorize=True`
(`lca_core/engine.py:1008-1014`, `lca_core/engine.py:1268-1273`). Comments state
that the retained forward LU would not be reused, so the engine intentionally
does not keep it. `tests/test_performance_instrumentation.py:118-124` locks this
in by asserting that the two implementations contain no
`lci(factorize=True)` call.

Conclusion: the design document's description of `factorize=True` is stale for
the shipped pipeline. Phase 1 should measure `lca.lci()` as the forward solve and
measure `adjoint_transpose_factorization` separately.

## 3. Matrix index maps

The engine uses Brightway 2.5's `lca.dicts` maps:

- scaling and direct activity contributions use `lca.dicts.activity`
  (`lca_core/engine.py:1022-1031`, `lca_core/engine.py:658-705`);
- biosphere inventory lookup uses `lca.dicts.biosphere`
  (`lca_core/engine.py:1033-1046`);
- contribution nodes map activity matrix indices through
  `lca.dicts.activity.reversed` via `_node_by_matrix_index()`
  (`lca_core/contribution_graph.py:45-47`,
  `lca_core/contribution_graph.py:182-186`);
- contribution edges correctly map `edge.product_index` through
  `lca.dicts.product.reversed`
  (`lca_core/contribution_graph.py:293-301`).

The adjoint seed enumerates the solved vector in product-index order and inserts
each value into the traversal solver's product-index cache
(`lca_core/contribution_graph.py:60-97`). The direct intensity right-hand side is
activity-indexed, while the solved cumulative intensity is product-indexed.

Empirically, the installed process-only `mock_background` and `bafu` databases
currently have equal activity-ID and product-ID sets. That is an implementation
accident which a persistent cache must not rely on. A cached vector must be
exported with `lca.dicts.product.reversed[index]`, not
`lca.dicts.activity.reversed[index]`.

Conclusion: the shipped contribution code distinguishes the two spaces at the
important traversal boundary. Phase 2 must preserve that distinction explicitly
when partitioning and comparing vectors.

## 4. Foreground/background discrimination

The direct-contribution table constructs a set of foreground Brightway node IDs
from the request-created activities, reverses each activity column to a node ID,
and treats membership in that set as foreground
(`lca_core/engine.py:672-705`). The relevant test is effectively:

```python
node_id in foreground_node_ids
```

The contribution graph receives a `foreground_metadata` dictionary keyed by the
same foreground activity IDs (`lca_core/engine.py:1058-1068`,
`lca_core/engine.py:1278-1288`). It classifies a traversed activity with:

```python
foreground = foreground_metadata.get(activity.id)
scope = "foreground" if foreground else "background"
```

See `lca_core/contribution_graph.py:182-198`.

This is explicit node-ID membership, not a database-name test or ID range. The
physical Sankey separately uses the YAML input's `database` field to identify
background links (`lca_core/engine.py:826-848`), but that is not the Step 6
matrix classification rule.

For Phase 2 column partitions, use the foreground activity-ID set against
`lca.dicts.activity`. For row partitions, independently reverse
`lca.dicts.product` and inspect the corresponding product nodes; do not reuse
activity matrix indices as product indices.

## 5. Adjoint implementation status

The adjoint is fully shipped production code.

- `factorize_adjoint()` calls
  `splu(lca.technosphere_matrix.T.tocsc())`
  (`lca_core/contribution_graph.py:55-57`).
- `_seed_adjoint_scores()` forms direct characterized intensities, solves the
  transposed system, and reconciles `y @ demand` with `lca.score`
  (`lca_core/contribution_graph.py:60-97`).
- The full calculation creates the transpose factorization only when contribution
  graphs are requested (`lca_core/engine.py:1015-1020`).
- Lazy Call 2 always creates it once per request
  (`lca_core/engine.py:1268-1277`) and passes it to each category traversal
  (`lca_core/engine.py:1293-1314`). Each category performs a new back-solve but
  shares the request's transpose LU.

Conclusion: Tier 1 moves an existing factorization and category back-solves; it
does not introduce the adjoint algorithm.

## 6. `ensure_ready()` and existing caches

`LCAEngine.ensure_ready()` delegates directly to `_ensure_databases()`
(`lca_core/api.py:29-30`). `_ensure_databases()`:

1. selects or installs the `lca_server` Brightway project and BAFU data;
2. removes the historical shared `foreground` scratch database;
3. installs or refreshes `mock_background`;
4. verifies or rebuilds the search projection; and
5. sets `_startup_databases_ready = True`.

See `lca_core/engine.py:113-161`.

Existing process-local state consists of:

- `_startup_databases_ready`, a one-time readiness Boolean
  (`lca_core/engine.py:58`, `lca_core/engine.py:113-121`);
- `_FLOW_INDEX`, a lazy biosphere-flow lookup map
  (`lca_core/engine.py:163-164`, `lca_core/engine.py:465-497`).

There is no existing factorization or intensity memo to extend. The search
projection has a useful database-fingerprint pattern based on name, number,
modified timestamp, backend, and dependencies
(`lca_core/search.py:393-430`, `lca_core/search.py:649-659`), but this is projection
freshness metadata, not a durable inventory version.

The two-call `result_id` is already shipped
(`lca_core/engine.py:1125-1137`, `lca_core/engine.py:1202-1206`,
`lca_core/engine.py:1333-1337`). Adding it is not part of this work.

## 7. Concurrency

Two module locks exist (`lca_core/engine.py:56-57`):

- `_db_lock` serializes startup database checks and uses a double-checked
  `_startup_databases_ready` flag (`lca_core/engine.py:113-121`);
- `_calculation_lock` is an `RLock` covering the full calculation and temporary
  database lifecycle (`lca_core/engine.py:636-647`,
  `lca_core/engine.py:961-970`, `lca_core/engine.py:1222-1227`).

A module-level cache can be read outside `_db_lock` only if entries are fully
built before being published and are immutable afterward. Lazy category
population and invalidation would introduce writes, so relying on bare dictionary
operations is not a sufficient lifecycle contract. Reuse `_db_lock` or add a
cache-specific lock for lookup-or-compute and invalidation. Request calculations
are currently serialized, but `ensure_ready()` and search-facing calls need not
hold `_calculation_lock`.

Recommended constraint: build a complete cache entry locally, publish it under a
lock, and never mutate its arrays. Publish a replacement entry on invalidation.

## 8. Test fixtures

`tests/test_mock_background_database.py:18-29` has a reusable setup pattern, not
a shared pytest fixture. Its `setUpClass()` creates `LCAEngine`, calls
`ensure_ready()`, and selects the Brightway project. The test confirms that the
mock installer is idempotent and contains four processes.

The same class-level setup can be used in the new `unittest` test modules.
Production APIs return serialized result data, not an `LCA` object, so the
standalone Phase 2 tests will need to use the private `_request_foreground()`
context and instantiate `bc.LCA` themselves. This requires no production-code
change and preserves automatic foreground cleanup.

The mock database itself is deterministic and versioned from
`mock_background/database.yaml`; its installer stores both
`mock_source_sha256` and `mock_schema_version`
(`lca_core/mock_database.py:67-101`, `lca_core/mock_database.py:148-157`).

## 9. Installed sizes and version metadata

Read-only measurements in the configured `lca_server` project produced:

| Database selection | Database nodes | Activity indices | Product indices | Matrix shape |
|---|---:|---:|---:|---:|
| `mock_background` | 4 | 4 | 4 | 4 x 4 |
| `bafu` | 11,947 | 11,947 | 11,947 | 11,947 x 11,947 |
| combined demand, both databases | 11,951 | 11,951 | 11,951 | 11,951 x 11,951 |

The combined measurement confirms that Brightway can assemble the disjoint union
needed for a database-set cache. A demand rooted only in one database loads that
database's technosphere block, not every installed background automatically.
Cache construction must therefore define the database set explicitly rather
than infer it from a single arbitrary demand.

At 25 categories, a dense `float64` matrix of all installed background product
intensities would occupy about 2.28 MiB
(`11,951 * 25 * 8` bytes), excluding dictionary/index overhead.

Installed metadata:

- `mock_background`: `mock_schema_version=2` and a SHA-256 source hash are
  available.
- `bafu`: `number=11947`, `modified`, `processed`, backend, and dependencies are
  available, but no source version or checksum is recorded.

The existing BAFU hardening plan already calls for version and source checksums
in Brightway metadata (`plans/PLAN_bafu_reimport_and_validation.md:192-198`).
Until that exists, Phase 3 needs an explicit decision: either add durable BAFU
identity metadata within approved scope, or approve a documented content
fingerprint. Name-only keying is not acceptable under the brief.

## Located BAFU-linked example set

There is a dedicated, tracked `bafu_examples/` directory:

| Fixture | Foreground processes | BAFU providers | Method |
|---|---:|---:|---|
| `bafu_examples/cotton_fiber_bafu.yaml` | 1 | 1 | TRACI v2.1 |
| `bafu_examples/plastic_broom.yaml` | 1 | 3 | EF v3.1 |
| `bafu_examples/polyester_tshirt_bafu.yaml` | 1 | 2 | TRACI v2.1 |
| `bafu_examples/wool_yarn_bafu.yaml` | 1 | 1 | TRACI v2.1 |

Equivalent product-catalog copies are tracked at:

- `product-graphs/cotton_fiber_bafu_linked.yaml`;
- `product-graphs/plastic_broom.yaml`;
- `product-graphs/polyester_tshirt_bafu_linked.yaml`; and
- `product-graphs/wool_yarn_bafu_linked.yaml`.

All four files in `bafu_examples/` were run through the current `run_base()` path
during reconnaissance. Each resolved its providers and returned both configured
LCIA categories successfully. This was a feasibility check, not a checked-in
golden baseline.

## Experimental-plan corrections requiring review

### Dataset correction for Task 2.1

All four tracked YAML files in `case_studies/` are foreground-only. Their
`A_BF` blocks are correctly empty, so they cannot pass the required
`A_BF.nnz > 0` non-vacuity assertion.

Recommended replacement:

- run the non-vacuous B1 test on all four tracked files in `bafu_examples/` and
  all three tracked files in `mock_examples/`;
- require at least one BAFU graph (`product-graphs/plastic_broom.yaml`) and one
  mock graph (`mock_examples/mock_plastic_broom.yaml`);
- optionally retain foreground-only cases as a separate assertion that there are
  no selected background columns, without calling that a B1 non-vacuity test.

### Dataset correction for Task 2.2

`case_studies/polyester_tshirt.yaml:35-53` contains only foreground exchanges.
The likely intended file is `bafu_examples/polyester_tshirt_bafu.yaml:15-22`,
which has two BAFU providers. It and `bafu_examples/plastic_broom.yaml` are valid
for testing different provider sets against the same BAFU database, but both
have a one-process foreground. They also specify different LCIA method families,
so the experiment must select one method/category available to the installed
background rather than blindly use each YAML's configured method.

Recommended two-part experiment:

1. Compare the BAFU slices from the two existing files under one explicitly
   selected method/category. This directly checks foreground-provider
   independence using repository fixtures.
2. If the stronger different-process-count condition remains required, compare
   the broom with a test-local two-process graph derived from it. Key both
   background slices by IDs from `lca.dicts.product.reversed`. This also changes
   foreground topology and matrix offsets.

### Characterization coverage correction for Phase 1

The proposed golden set covers mock-linked examples but no tracked BAFU-linked
graph. Add the four files in `bafu_examples/` to the explicit golden manifest so
the future Tier 1 BAFU path is characterized before implementation.

Use an explicit checked-in manifest rather than an unrestricted filesystem glob.
This checkout currently contains the user's untracked
`case_studies/acid_blue_25.yaml`, which references an uninstalled
`ecoinvent_cutoff` database. It is not part of `main` and must remain untouched;
including it accidentally would make local golden generation fail for an
unrelated reason.

### Timing-label correction for Phase 1

Record the existing `lci_factorization` phase as the current forward
`lca.lci()` work, despite the historical label, and separately record
`adjoint_transpose_factorization`. Do not change the forward call to
`factorize=True` as part of baseline creation.

## Proposed next gate

After review of the four corrections above:

1. implement only Phase 1 characterization tests and baseline measurements;
2. verify they pass without production-code changes;
3. implement the three standalone Phase 2 experiments with corrected datasets;
4. stop again with exact numerical findings before any cache code is written.

Tier 2 remains instruction-gated. Tier 3, result-ID caching, renderer/search
changes, and dependency upgrades remain out of scope.
