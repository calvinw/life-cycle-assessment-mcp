# Plan: Lazy Calculate — Two-Call LCA API

Status: Proposed
Date: July 28, 2026

Supersedes the framing in
[`PLAN_eager_background_graph_bundle.md`](PLAN_eager_background_graph_bundle.md)
and refines
[`PLAN_two_stage_lca_background_topology.md`](PLAN_two_stage_lca_background_topology.md).
Those remain useful for their cutoff and topology analysis.

## Objective

Split `run_lca` into two calls so the webapp shows inventory and total impact
scores in a few seconds, and pays for contribution detail only when a user
opens it.

- **Call 1** returns inventory, LCIA totals, scaling vector, direct scores, and
  bounded background topology.
- **Call 2** returns the contribution graph for one impact category, serving
  both the contribution tree and the Sankey.

Both calls are stateless. No sessions, no server-side result cache, no polling.

## Why

From `benchmarks/background_graph_phase0.md`, measured on the real BAFU
examples:

| | Time | Payload (raw / gzip) |
|---|---:|---:|
| LCIA only (no contribution graphs) | 2.5–2.8 s | ~100 KB |
| All nonzero categories | 27–98 s | 3.6–12.0 MB / 446 KB–1.4 MB |
| One category | 0.5–5.6 s | 27 KB–1.1 MB / 4–130 KB |

`plastic_broom.yaml` is the worst case: **98 s and 12 MB** for 25 categories.

Payload is the stronger argument, not time. A 12 MB JSON parse on every
Calculate is unacceptable in the browser regardless of how fast the server
gets. Per-category responses are 4–130 KB gzipped, which is trivially lazy.

Users typically open two or three categories, not twenty-five.

## Current Behaviour

`lca_core/engine.py::run_analysis` (line 837) does everything in one pass:

1. `_request_foreground` (line 576) creates a uniquely-named temporary
   Brightway foreground database, under the global `_calculation_lock`.
2. One `bc.LCA`, one `lci(factorize=True)` (line 868).
3. Loops LCIA methods with `switch_method` + `lcia()` (lines 915–918).
4. `_contribution_category` (line 594) computes direct scores.
5. `build_contribution_graph` for each YAML-requested category (line 926).
6. `_build_sankey` from the scaling vector (line 963).
7. Deletes the temporary foreground database.

The webapp currently fakes laziness at `product-graph-editor/src/App.tsx:323`
(`loadCategory`): it rewrites the YAML to request a single category and calls
the full `run_lca` again. This works but pays the complete setup cost per
category open.

## Call 1 — Base Result

```
POST /api/lca/base
{ "product_graph": "<yaml>" }
```

Returns:

- `lci` — aggregated inventory (unchanged contract)
- `lcia` — total score per category (unchanged contract)
- `scaling_vector` — unchanged contract
- `process_contributions` — direct scores, **now including background
  activities** (see below)
- `background_topology` — bounded physical graph for local expansion
- `sankey` — the existing YAML-derived flow Sankey (cheap, keep it here)
- `result_id` — content hash, see "Forward compatibility"

Does **not** return: `contribution_graphs`.

Implementation is largely `run_analysis` with step 5 removed. Reuse the same
`_request_foreground` / single-factorization lifecycle.

### Background direct scores are already free

`_contribution_category` (line 602) computes:

```python
column_totals = np.asarray(lca.characterized_inventory.sum(axis=0)).ravel()
```

This is the direct score of **every activity in the system**, foreground and
background. The current code then iterates only `spec["processes"]`
(line 609) and rolls everything else into `residual_score`.

Change: also walk the nonzero entries of `column_totals`, map indices back
through `lca.dicts.activity`, and emit background rows with
`scope: "background"`.

This requires no additional solves. It decouples the direct-contributions
table from graph traversal entirely — today background direct rows only exist
because `run_analysis` copies them out of
`graph["activity_contributions"]` (lines 935–944).

Keep the existing reconciliation check (line 636): foreground + background +
residual must equal `total_score`.

### Background topology bounds

Bound by **topology limits only** — max depth, max unique activities, max
technosphere exchanges, max direct biosphere records.

Do **not** cut by exchange amount magnitude. The background graph mixes kg,
kWh, tkm, and m³; comparing raw magnitudes across units silently privileges
some units over others. This point is developed further in
`PLAN_two_stage_lca_background_topology.md`.

Do **not** cut by impact cutoff either — that is category-specific work that
Call 1 exists to defer.

The payload must record which limit stopped the walk, so the webapp can say
"bounded here" rather than implying the graph is complete.

## Call 2 — Contribution Graph

```
POST /api/lca/contribution
{ "product_graph": "<yaml>", "category": "climate change | GWP100",
  "result_id": "<optional>" }
```

Returns one `ContributionGraph` in the existing schema-3 shape from
`lca_core/contribution_graph.py`. No changes to that contract — the webapp's
`loadedGraphs` map already consumes exactly this.

Stateless: re-parse the YAML, rebuild the foreground, re-run
`lci(factorize=True)`, `switch_method`, `lcia()`, then traverse. That repeats
~2.7 s of setup that a stateful server would not need. Accept this for the
first implementation.

The same graph serves both the contribution tree and the impact Sankey. Do
not build a separate Sankey endpoint.

## Optimization To Test First

**Do this spike before building the API split.** It may change the cost
picture enough to alter the design.

`build_contribution_graph` uses
`bw_graph_tools.NewNodeEachVisitGraphTraversal`
(`lca_core/contribution_graph.py:108`), which re-solves the linear system at
each node it visits. The benchmark's "Calculations" column is that count:
**796** for one category of `plastic_broom.yaml`, **923** for one category of
`wool_yarn_bafu.yaml`.

All of those collapse into **one** solve per category:

Solve the adjoint system once,

```
Aᵀ y = Bᵀ c
```

where `c` is the characterization vector for the category. `y_i` is then the
cumulative impact per unit output of activity `i`. The cumulative score of any
occurrence in the tree is `y_i × supply_amount_of_that_occurrence`, and the
score on edge `i → j` is `y_i × a_ij × s_j`. Traversal becomes sparse
arithmetic over `A` plus cutoff bookkeeping — no solves at all.

Per-category traversal should drop from ~4 s to near zero, leaving Call 2
dominated by the ~2.7 s setup.

### Snag to check

`lci(factorize=True)` factorizes `A`; the adjoint needs `Aᵀ`.

- With scipy SuperLU this is free: `splu_object.solve(b, trans='T')`.
- With pypardiso you will likely need a second factorization of `A.T`. Still
  one factorization instead of ~800 solves, so the win holds either way.

Validate against a BAFU example: the adjoint-derived cumulative scores must
match the current traversal's `cumulative_score` values within tolerance
before this replaces anything.

If this works, eager becomes viable on time grounds again — but stay lazy
anyway, because the 12 MB payload problem is unaffected.

## Forward Compatibility: `result_id`

Call 1 returns `result_id = hash(normalized_yaml + method_name)`. Call 2
accepts it optionally.

**Initially the engine ignores it and recomputes every time.** Fully
stateless.

If the ~2.7 s per-category setup later becomes the bottleneck, the foreground
database and factorization can be cached behind that key with a TTL, falling
back to full rebuild on miss. Neither the API contract nor the client changes.

Adding the field now costs nothing; retrofitting it means a client change
later.

## Concurrency Note

`_request_foreground` holds a global `_calculation_lock` for the whole
calculation. Splitting into two calls increases request count, so lock
contention gets worse, not better: a Call 2 can block a Call 1.

Not blocking for single-user work. Worth measuring before any multi-user
deployment. Independent of this plan, but the two-call split makes it
more visible.

## Migration

Keep `run_lca` (`/api/lca/run`) working unchanged. It is registered in
`REST_TOOL_ROUTES` (`lca_server.py:59`), used by MCP clients, and useful for
scripted full exports.

Add the two new tools alongside it, registered the same way so
`/api/tools` discovery keeps working — the webapp resolves endpoints through
that list (`product-graph-editor/src/lib/lcaApi.ts:222`).

## Sequencing

1. **Spike the adjoint solve** on one BAFU example. Verify cumulative scores
   match the current traversal. Decide whether to adopt it before the split.
2. **Background direct scores** from `characterized_inventory` column totals.
   Small, independent, testable on its own. Extends
   `process_contributions` without touching traversal.
3. **`/api/lca/base`** — `run_analysis` minus contribution graphs, plus
   background topology and `result_id`.
4. **`/api/lca/contribution`** — single-category, stateless.
5. **Frontend** — `previewYaml` (`src/App.tsx:1566`) calls Call 1;
   `loadCategory` (`src/App.tsx:323`) calls Call 2 instead of rewriting YAML
   and re-running `calculateLca`. The existing `appliedRevision` counter
   already handles discarding stale responses.

Steps 1 and 2 are independent of each other and of the API split.

## Verification

- Call 1 + Call 2 for a category must produce numerically identical values to
  today's single `run_lca` with that category requested. Assert this in tests
  against the mock examples, which run in ~0.16 s.
- Re-run `scripts/benchmark_background_graphs.py` after the split and record
  Call 1 and Call 2 times separately.
- The reconciliation invariant in `_contribution_category` must still hold
  once background rows are added.
