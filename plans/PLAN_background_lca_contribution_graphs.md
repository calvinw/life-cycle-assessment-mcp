# Plan: Background LCA Contribution Graphs in a Single `run_lca` Request

## Status

Proposed.

## Summary

Extend `run_lca` so a product graph that links to BAFU or another background
database can return an impact contribution graph from the functional unit,
through the foreground, and into the background supply chain until an
impact-relative cutoff, depth limit, or calculation limit is reached.

The implementation must reuse the `LCA` object already created by
`run_analysis`. It must not rebuild the temporary foreground database or invoke
`run_lca` separately for PLA, nylon, freight, or other immediate background
inputs.

`bw_graph_tools.NewNodeEachVisitGraphTraversal` will perform the impact-first
traversal. It accepts an LCA object for which LCI and LCIA have already been
calculated. The traversal can perform internal cached branch solves to compute
cumulative scores, but the client makes one `run_lca` request and the engine
performs one root inventory calculation.

---

## Problem Statement

The plastic broom example contains one foreground assembly process and three
BAFU inputs:

- 0.52 kg of global PLA;
- 0.03 kg of European Nylon 6; and
- 0.1055 tonne-kilometres of European freight transport.

The numerical LCA includes the complete BAFU supply chains, but the current
result contract does not expose their process contributions:

1. `_contribution_category` iterates only over processes declared in the YAML.
2. All background impact is combined into `residual_score`.
3. `_build_sankey` renders the declared foreground structure and immediate
   background providers, but does not recursively traverse those providers.
4. `get_bafu_svg` has recursive cutoff traversal, but it starts a separate LCA
   for one background activity instead of reusing the product-system LCA.
5. `get_contributions` returns a flat top-process list, starts a fresh LCA, and
   is not exposed as an MCP tool.

As a result, clients cannot ask one `run_lca` call for the contribution path:

```text
1 plastic broom
  -> Plastic broom assembly
    -> PLA
      -> natural gas
      -> corn farming
      -> electricity
      -> ...
    -> Nylon 6
      -> ...
    -> freight
      -> ...
```

The temporary workaround is to run isolated PLA, nylon, and freight models and
add their results. That is inefficient, loses the connected supply-chain
structure, and should not be required.

---

## Diagnosis

This is not a Brightway calculation error. The total inventory and LCIA scores
are correct. It is a limitation of the application engine's result builder and
public contract.

The existing implementation already computes the inventory and factorized
scaling solution once:

```python
lca = bc.LCA(demand={ref_act: fu_amount}, method=method_tuples[0])
lca.lci(factorize=True)
```

It then switches LCIA methods on the same object. The missing step is to run a
category-specific contribution traversal on that object after `lca.lcia()` and
before the temporary foreground database is removed.

The current residual-only behavior is explicitly documented and tested, so the
fix requires a versioned result-contract change rather than an incidental code
change.

---

## Goals

1. Return foreground and background process contributions from one
   `run_lca` request.
2. Traverse from the functional unit through the complete connected product
   system.
3. Stop traversal using an impact-relative cutoff, maximum depth, and maximum
   calculation count.
4. Preserve both direct/exclusive and cumulative impact scores without double
   counting.
5. Report the impact not represented by visited direct process scores as a
   residual.
6. Preserve negative contributions and signed percentages.
7. Give repeated visits to the same activity distinct occurrence IDs while
   retaining a stable activity identity for aggregation.
8. Keep existing product graphs and clients working when contribution traversal
   is not requested.
9. Make the plastic broom a regression fixture for background contribution
   behavior.

---

## Non-Goals

- Changing the underlying BAFU inventories or EF v3.1 characterization factors.
- Replacing Brightway's matrix solver.
- Treating cumulative node scores as additive.
- Traversing every EF v3.1 category by default.
- Combining physical Sankey widths across incompatible units.
- Redesigning the unit-process SVG cards.
- Adding allocation or substitution policies beyond what the active Brightway
  database already defines.

---

## Key Design Decision: Separate Amount and Impact Graphs

The existing `sankey` is a physical-flow graph. Its links contain quantities
such as kilograms, tonne-kilometres, and units. It should remain separate from
the impact contribution graph.

Add a new top-level result field named `contribution_graphs`. Each entry is tied
to one LCIA category and contains impact scores, cutoff metadata, traversal
nodes, traversal edges, and coverage information.

Do not overload physical Sankey link widths with LCIA scores.

---

## Product Graph Configuration

Add an optional contribution section under `lcia`:

```yaml
lcia:
  method_name: "EF v3.1"
  contribution_graph:
    categories:
      - climate change
      - acidification
    cutoff: 0.01
    biosphere_cutoff: 0.001
    max_depth: 6
    max_calculations: 1000
```

Rules:

- `categories` substring-matches the full category labels already returned in
  `lcia`.
- An ambiguous or missing category match is a validation error with the
  available labels included in the message.
- `cutoff` is a fraction of the absolute total category score and must be in
  `(0, 1)`.
- `biosphere_cutoff` controls which individual elementary flows are emitted as
  graph flow nodes.
- `max_depth` limits unrolled path depth from the functional unit.
- `max_calculations` prevents an unexpectedly large traversal.
- If `contribution_graph` is absent, preserve current calculation time and
  response size.

Request-level overrides can be added later, but the initial implementation
should keep analysis configuration in the YAML so examples are reproducible.

---

## Proposed Result Contract

Bump `result_schema_version` from `2` to `3` when
`contribution_graphs` is introduced.

Retain the existing `process_contributions` and `sankey` fields during the
migration. `process_contributions` keeps its current foreground-plus-residual
semantics until consumers have moved to the new graph contract.

Example:

```json
{
  "result_schema_version": 3,
  "lcia": {
    "climate change | global warming potential (GWP100)": {
      "score": 1.7089725,
      "unit": "kg CO2-Eq"
    }
  },
  "contribution_graphs": [
    {
      "id": "impact-graph:...",
      "label": "climate change | global warming potential (GWP100)",
      "unit": "kg CO2-Eq",
      "total_score": 1.7089725,
      "cutoff": 0.01,
      "biosphere_cutoff": 0.001,
      "max_depth": 6,
      "max_calculations": 1000,
      "calculation_count": 42,
      "coverage": 0.97,
      "residual_score": 0.051,
      "nodes": [],
      "edges": [],
      "flows": [],
      "activity_contributions": []
    }
  ]
}
```

### Process occurrence node

```json
{
  "id": "occurrence:...",
  "activity_id": "activity:bafu:273090",
  "database": "bafu",
  "code": "273090",
  "process_name": "Polylactide, granulate, at plant",
  "location": "GLO",
  "scope": "background",
  "depth": 2,
  "supply_amount": 0.52,
  "unit": "kilogram",
  "direct_score": 0.12,
  "cumulative_score": 1.407,
  "cumulative_percentage": 82.35,
  "terminal": false
}
```

Definitions:

- `id` identifies this occurrence in the unrolled traversal tree.
- `activity_id` identifies the underlying Brightway activity and is shared by
  repeated occurrences of the same activity.
- `direct_score` is the characterized direct biosphere impact for this
  occurrence and supply amount.
- `cumulative_score` includes this occurrence and its upstream supply chain.
- `cumulative_percentage` is `cumulative_score / total_score * 100`.
- `scope` is `foreground` or `background`.
- `terminal` means traversal stopped at this occurrence because of cutoff,
  depth, calculation limit, or no further technosphere inputs.

### Traversal edge

```json
{
  "id": "impact-edge:...",
  "source": "occurrence:producer",
  "target": "occurrence:consumer",
  "flow_name": "Polylactide, granulate, at plant",
  "amount": 0.52,
  "unit": "kilogram"
}
```

### Aggregated activity contribution

The occurrence graph can contain the same activity more than once. Also return
an activity-level table formed by summing occurrence `direct_score` values for
the same `activity_id`:

```json
{
  "activity_id": "activity:bafu:273090",
  "process_name": "Polylactide, granulate, at plant",
  "location": "GLO",
  "scope": "background",
  "direct_score": 0.18,
  "percentage": 10.5
}
```

This table is additive. The graph's cumulative scores are not additive.

---

## Cutoff and Reconciliation Semantics

`NewNodeEachVisitGraphTraversal` unrolls the graph and returns:

- `cumulative_score`;
- `direct_emissions_score`;
- `remaining_cumulative_score_outside_specific_flows`; and
- separate characterized biosphere flows when requested.

Use these values directly rather than recomputing cumulative scores in the
renderer.

For each category:

```text
traversed_direct_score =
  sum(direct_score for every visited process occurrence)

residual_score =
  total_score - traversed_direct_score

coverage =
  traversed_direct_score / total_score
```

Reconciliation must satisfy:

```text
traversed_direct_score + residual_score == total_score
```

within the existing numeric tolerances.

Important rules:

- Never sum `cumulative_score` across nodes; parent cumulative scores contain
  child impacts.
- Apply cutoff comparisons using absolute score, but preserve the signed score
  in results.
- Do not clamp negative scores or percentages.
- If the total category score is effectively zero, return an empty graph with
  `status: "zero_total"` rather than invoking a traversal that requires a
  non-zero total.
- Report whether traversal stopped because of `max_depth` or
  `max_calculations`.
- A residual is expected whenever cutoff, depth, or calculation limits omit
  part of the product system.

---

## Engine Architecture

### 1. Add a renderer-neutral traversal adapter

Create `lca_core/contribution_graph.py` with functions that:

1. Validate and resolve requested impact categories.
2. Run `NewNodeEachVisitGraphTraversal` against the already-active `lca`.
3. Resolve matrix indices to Brightway activities and reference products.
4. Classify activities as foreground or background.
5. Convert Brightway traversal objects into typed JSON-safe dictionaries.
6. Generate stable activity IDs and deterministic occurrence/edge IDs.
7. Aggregate direct scores by activity.
8. Calculate coverage and residual score.
9. Enforce finite numbers and reconciliation.

This module must not create a new `bc.LCA`, rebuild a foreground database, or
switch Brightway projects.

### 2. Integrate traversal inside `run_analysis`

The integration point is inside the existing LCIA loop:

```python
for method_tuple in method_tuples:
    lca.switch_method(method_tuple)
    lca.lcia()
    record_lcia_total()
    record_foreground_contributions()

    if method_tuple matches a requested contribution category:
        contribution_graphs.append(
            build_contribution_graph(
                lca=lca,
                ...
            )
        )
```

This must run before `_request_foreground` exits because traversal needs the
temporary foreground activities and their metadata.

### 3. Reuse traversal logic across entry points

Refactor `background_svg.py` so it consumes the new renderer-neutral graph
instead of owning a second mapping and traversal implementation.

`get_bafu_svg` can continue creating its own LCA when called independently for
a database activity. `run_lca`, however, must pass its existing LCA into the
shared traversal adapter.

### 4. Replace the fresh-LCA contribution helper

Refactor `get_contributions` to either:

- derive its flat ranking from a returned contribution graph; or
- call the same adapter from a shared internal calculation context.

Do not leave two definitions of process contribution scores with different
cutoff or aggregation semantics.

---

## MCP, REST, and Python API Changes

### MCP

`run_lca(product_graph)` remains callable with the same argument. Requested
contribution graphs come from the YAML configuration.

Update the tool description and output schema to explain:

- graphs are category-specific;
- direct scores are additive;
- cumulative scores are not additive;
- background processes are included to cutoff; and
- residual score represents omitted direct impact.

### REST

`POST /api/lca/run` continues accepting the product graph. Return
`contribution_graphs` when configured.

Update the OpenAPI schema and examples.

### Python

Add typed contracts in `lca_core/models.py` for:

- `ContributionGraph`;
- `ContributionNode`;
- `ContributionEdge`;
- `ContributionFlow`; and
- `ActivityContribution`.

Update `LcaCoreResult` and `LcaResult` to schema version 3.

---

## Renderer Changes

The existing physical `sankey` and its SVGs remain unchanged initially.

Add an impact contribution SVG renderer that consumes
`contribution_graphs[n]`. It should show:

- foreground and background process styling;
- cumulative impact and percentage on process nodes;
- exchange name, amount, and unit on edges;
- cutoff/depth terminal indicators;
- residual/coverage in the title or legend; and
- important biosphere flows when enabled.

Do not make SVG generation the source of graph calculations. JSON graph data
is authoritative; rendering is a pure presentation step.

---

## Plastic Broom Migration

Update `bafu_examples/plastic_broom.yaml` to request:

```yaml
lcia:
  method_name: "EF v3.1"
  contribution_graph:
    categories:
      - climate change
      - acidification
    cutoff: 0.01
    max_depth: 6
```

Expected behavior from one `run_lca` request:

1. The functional unit is one plastic broom.
2. The graph includes the foreground assembly process.
3. The graph includes PLA, Nylon 6, and freight as background nodes.
4. The graph continues into their BAFU suppliers until the configured cutoff.
5. The climate graph reports approximately 1.709 kg CO2-Eq in total for the
   current database snapshot.
6. PLA is the largest first-level cumulative contributor.
7. Direct visited process scores plus residual reconcile to the total.
8. No isolated single-input LCA runs are required.

---

## Implementation Phases

### Phase 1 — Contract and traversal adapter

1. Define contribution configuration validation.
2. Add schema-version-3 typed result models.
3. Implement matrix-index and Brightway-activity resolution.
4. Implement traversal conversion, stable IDs, coverage, and residual.
5. Unit-test conversion using small mock traversal objects.

### Phase 2 — Engine integration

1. Call the adapter from the existing LCIA loop.
2. Reuse the factorized LCI state already created by `run_analysis`.
3. Ensure traversal occurs before foreground cleanup.
4. Add zero-total and traversal-limit handling.
5. Keep results deterministic across repeated calls.

### Phase 3 — Public interfaces

1. Update MCP output schemas and descriptions.
2. Update REST/OpenAPI schemas.
3. Update Python typed API.
4. Document schema-version migration and backward compatibility.

### Phase 4 — Rendering

1. Refactor the BAFU SVG path to consume the common contribution graph.
2. Add product-system contribution SVG generation.
3. Verify Graphviz output and labels at multiple cutoffs and depths.

### Phase 5 — Examples and documentation

1. Update the plastic broom example.
2. Add a background-backed storage-bin or textile example with a different
   supply-chain shape.
3. Update the REST and MCP guides with one-request examples.
4. Remove documentation that presents background impact only as an opaque
   residual for schema version 3.

---

## Test Plan

### Numerical correctness

- Full LCIA totals remain unchanged with contribution graphs enabled.
- Plastic broom climate total remains approximately 1.709 kg CO2-Eq for the
  current BAFU snapshot.
- Visited direct scores plus residual reconcile for every requested category.
- Negative direct and cumulative scores retain their signs.
- Zero-total categories return `status: "zero_total"`.

### Traversal behavior

- Lowering cutoff never reduces visited-node coverage.
- Increasing `max_depth` never removes an already-visited shallower node.
- `max_calculations` is enforced and reported.
- Repeated visits to one activity have distinct occurrence IDs and one stable
  activity ID.
- Foreground and background scope classification is correct.
- Cyclic background systems terminate under traversal limits.

### Performance and lifecycle

- Assert one temporary foreground database is created for one `run_lca`.
- Assert one root `bc.LCA` object and one `lci(factorize=True)` call are used.
- Allow and report internal traversal calculation count.
- Assert the temporary foreground database is deleted after success or failure.
- Compare runtime and response size at cutoffs of 5%, 1%, and 0.1%.

### API compatibility

- Existing YAML without `contribution_graph` still calculates.
- Existing `lcia`, `lci`, `scaling_vector`, `process_contributions`, and
  `sankey` fields remain present during migration.
- MCP discovery exposes the nested schema for contribution graphs.
- REST serialization contains only finite JSON numbers.

### Renderer verification

- Every edge endpoint exists in `nodes`.
- Cumulative scores shown in SVG match JSON.
- Coverage and residual labels match JSON.
- Physical Sankey rendering remains unchanged.

---

## Files Expected to Change

| File | Change |
|---|---|
| `lca_core/contribution_graph.py` | New shared traversal and conversion module |
| `lca_core/engine.py` | Validate config and build graphs inside the existing LCIA loop |
| `lca_core/models.py` | Add schema-version-3 contribution graph contracts |
| `lca_core/background_svg.py` | Consume shared graph data instead of owning traversal mapping |
| `lca_core/api.py` | Unify flat contribution analysis with the graph adapter |
| `lca_server.py` | Update MCP and REST schemas, routes, and tool documentation |
| `bafu_examples/plastic_broom.yaml` | Request climate and acidification graphs |
| `tests/test_lca_results_extension.py` | Replace residual-only expectation with graph assertions |
| `tests/test_background_contribution_graph.py` | New traversal, cutoff, reconciliation, and lifecycle tests |
| `docs/llm_rest_api_guide.md` | Document the new result and one-request workflow |
| `docs/rest_api.md` | Document schema version 3 |

---

## Risks and Mitigations

### Large response payloads

Mitigation: contribution graphs are opt-in and category-filtered. Enforce
cutoff, maximum depth, and maximum calculations.

### Double counting

Mitigation: clearly separate additive direct scores from non-additive cumulative
scores. Reconcile using visited direct scores only.

### Repeated activities

Mitigation: use occurrence IDs for the unrolled graph and stable activity IDs
for aggregation.

### Negative or near-zero totals

Mitigation: preserve signs, use absolute cutoff comparisons, and return an
explicit zero-total status when traversal is undefined.

### Foreground cleanup

Mitigation: perform traversal inside `_request_foreground` and retain existing
success/failure cleanup tests.

### Traversal cost

Mitigation: reuse the factorized root LCI, expose `calculation_count`, benchmark
cutoffs, and avoid generating graphs for unrequested categories.

---

## Acceptance Criteria

The work is complete when:

1. One MCP `run_lca` call on the configured plastic broom YAML returns total
   EF v3.1 results and recursive climate and acidification contribution graphs.
2. No second `run_lca` call or isolated PLA, nylon, or freight model is used.
3. Both foreground and BAFU background processes appear in the same graph.
4. Traversal honors cutoff, biosphere cutoff, maximum depth, and maximum
   calculation count.
5. Direct scores plus residual reconcile to the LCIA total within numeric
   tolerances.
6. Cumulative scores are documented and never summed as exclusive
   contributions.
7. The graph and flat activity aggregation handle repeated activities without
   identity collisions or double counting.
8. Existing unconfigured product graphs continue to calculate.
9. Tests verify a single root inventory calculation and correct foreground
   cleanup.
10. MCP, REST, Python, and documentation all expose the same versioned result
    semantics.
