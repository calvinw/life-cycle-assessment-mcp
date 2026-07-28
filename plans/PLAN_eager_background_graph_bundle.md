# Plan: Eager Multi-Category Background Graph Bundle

Status: Proposed  
Date: July 27, 2026  
Coordinated frontend plan:
[`product-graph-editor/plan/eager-background-contribution-graphs.md`](../../product-graph-editor/plan/eager-background-contribution-graphs.md)

## Objective

Extend `run_lca` so one calculation can return a complete, bounded background
supply-chain graph with direct, cumulative, and unexpanded scores for the impact
categories requested by the client.

After `run_lca` returns, the webapp must be able to:

- expand contribution trees;
- expand process and elementary-flow table rows;
- switch impact categories;
- render impact-oriented supply-chain diagrams;
- aggregate repeated occurrences by activity; and
- inspect every process and emission included by the configured cutoffs

without another request to the engine.

The target is one Calculate action followed by local exploration. Opening a
result view must never start a second complete LCA.

## Scope of "Complete Graph"

The BAFU technosphere graph is cyclic and cannot be returned as a literal
unbounded tree. "Complete" means the full occurrence graph returned by
Brightway within explicit limits:

- impact-relative cutoff;
- biosphere-flow cutoff;
- maximum depth;
- per-category and total calculation limits;
- union-node limit; and
- emission-record limit.

The response must preserve omitted impact as `unexpanded_score` and identify
which limit stopped traversal. A bounded partial graph is acceptable; silently
discarding impact is not.

## Current Implementation

The engine already has the essential one-category implementation.

### Existing calculation lifecycle

`lca_core/engine.py`:

1. creates an isolated temporary foreground database;
2. creates one `bw2calc.LCA`;
3. calls `lci(factorize=True)` once;
4. switches LCIA methods on the same LCA;
5. computes LCIA totals and foreground process contributions;
6. invokes `build_contribution_graph` only for YAML-requested categories; and
7. removes the temporary foreground database.

Existing tests verify that a graph-enabled `run_lca` creates only one root
`bc.LCA`.

### Existing traversal and serialization

`lca_core/contribution_graph.py` uses:

```python
NewNodeEachVisitGraphTraversal(
    lca,
    GraphTraversalSettings(
        cutoff=...,
        biosphere_cutoff=...,
        max_calc=...,
        max_depth=...,
        separate_biosphere_flows=...,
    ),
)
```

The installed versions are:

- `brightway25 1.1.1`;
- `bw2calc 2.5.0`;
- `bw2data 4.7`; and
- `bw-graph-tools 0.9`.

Each existing category graph contains:

- occurrence-specific process nodes;
- producer/consumer edges;
- direct scores;
- Brightway cumulative scores;
- cumulative percentages;
- node and graph unexpanded scores;
- terminal flags;
- characterized elementary flows;
- stable activity identities;
- occurrence counts and activity-level direct-score aggregation;
- traversal calculation count; and
- coverage/status.

This is already sufficient for local browser expansion when the graph was
requested in the original YAML.

### Existing limitations

- Graphs are opt-in through `lcia.contribution_graph.categories`.
- `POST /api/lca/run` accepts only `product_graph`.
- Each requested category returns a separate graph with duplicated topology and
  metadata.
- Occurrence IDs include the category label and traversal-local unique ID, so
  the same physical occurrence cannot currently be merged across categories.
- The shallow `sankey` is created from YAML plus direct background providers; it
  does not recursively traverse BAFU.
- The server does not currently appear to compress REST JSON responses.
- `max_calculations` is not an exact node limit.
- Status does not distinguish impact cutoff, maximum depth, calculation limit,
  node limit, flow limit, or total-request budget.

## Feasibility Measurements

Benchmarks used the current local engine and BAFU Plastic Broom climate-change
graph.

| Impact cutoff | Coverage | Nodes | Edges | Flows | Time | Graph raw | Graph gzip |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1% | 64.8% | 42 | 41 | 22 | 4.1 s | 65 KB | 8.9 KB |
| 0.5% | 71.2% | 85 | 84 | 39 | 5.0 s | 131 KB | 17.9 KB |
| 0.1% | 81.0% | 249 | 248 | 99 | 6.4 s | 369 KB | 47.5 KB |
| 0.05% | 84.1% | 439 | 438 | 160 | 7.7 s | 637 KB | 80.5 KB |
| 0.01% | 86.8% | 1,003 | 1,002 | 457 | 8.7 s | 1.45 MB | 177 KB |

The 0.01% run used a 0.001% biosphere cutoff and stopped at the
1,000-calculation limit. Its complete core result, excluding REST SVG strings,
was 1.62 MB raw and 209 KB gzipped.

The current Simple Mock Plastic Broom graph was:

- 5 nodes;
- 4 edges;
- 3 flows;
- 0.46 seconds locally;
- 7.6 KB raw; and
- 1.3 KB gzipped.

### 1,500 emission records

In the measured large graph, 457 serialized flow records occupied approximately
188 KB raw, or about 410 bytes per record. At the same representation, 1,500
flow records would occupy about 615 KB raw before compression.

Returning 1,000 process occurrences plus 1,500 emission records for one graph is
reasonable. Storing both direct and cumulative scores is not the size problem.

### Twenty-five impact categories

For 1,000 shared nodes:

```text
1,000 nodes
× 25 categories
× 2 values (direct and cumulative)
= 50,000 numeric values
```

Compact arrays for 50,000 numbers are reasonable. Repeating all node names,
activity metadata, edges, and physical quantities 25 times is not.

The worst case is also not necessarily 1,000 shared nodes. If every category
visits a different set of 1,000 occurrences, the union could approach 25,000
nodes. A global union-node and total-calculation budget is therefore required.

## Recommended Target Contract

Introduce result schema version 4 with one shared background graph bundle and
category-indexed score overlays.

### Request

Separate result shaping from the product YAML:

```json
{
  "product_graph": "...",
  "result_options": {
    "background_graph": {
      "mode": "all_nonzero",
      "categories": [],
      "cutoff": 0.001,
      "biosphere_cutoff": 0.0001,
      "max_depth": 12,
      "max_calculations_per_category": 1000,
      "max_total_calculations": 5000,
      "max_union_nodes": 2500,
      "max_flow_records": 5000,
      "include_flows": true
    }
  }
}
```

Modes:

- `none`: no recursive background bundle;
- `explicit`: only named categories;
- `all_nonzero`: all categories with a numerically nonzero LCIA total; and
- `yaml`: existing `lcia.contribution_graph` behavior for compatibility.

Skip background traversal entirely when the resolved product graph has no
background providers.

### Category table

Return categories once and identify score-vector positions:

```json
{
  "categories": [
    {
      "id": "impact:ef-v3-1:...",
      "label": "climate change | global warming potential (GWP100)",
      "unit": "kg CO2-Eq",
      "total_score": 0.9455,
      "status": "partial",
      "coverage": 0.87,
      "unexpanded_score": 0.12,
      "calculation_count": 1001,
      "truncation_reasons": ["max_calculations"]
    }
  ]
}
```

### Shared occurrence nodes

```json
{
  "id": "occurrence:path-stable-id",
  "activity_id": "background-process:...",
  "process_name": "Mock polypropylene granulate, at plant",
  "database": "mock_background",
  "code": "mock-polypropylene",
  "location": "MOCK",
  "scope": "background",
  "depth": 2,
  "supply_amount": 0.52,
  "unit": "kilogram",
  "category_membership": [true, true],
  "direct_scores": [0.42, 0.003],
  "cumulative_scores": [0.89, 0.014],
  "unexpanded_scores": [0.01, 0.002],
  "terminal_by_category": [false, false]
}
```

Use arrays rather than repeating category IDs on every node. The category table
defines array positions.

The engine remains authoritative for cumulative values. Browsers may aggregate
or format them but should not reconstruct Brightway traversal semantics.

### Shared edges

Physical producer/consumer relationships and quantities are category
independent and should be returned once:

```json
{
  "id": "edge:path-stable-id",
  "source": "producer-occurrence",
  "target": "consumer-occurrence",
  "flow_name": "Electricity, medium voltage",
  "amount": 2.5,
  "unit": "kilowatt hour",
  "category_membership": [true, false]
}
```

### Shared elementary-flow records

Merge flows by occurrence plus biosphere-flow identity:

```json
{
  "id": "flow:path-stable-id",
  "process_occurrence_id": "occurrence:path-stable-id",
  "flow_id": "biosphere:...",
  "flow_name": "Carbon dioxide, fossil",
  "categories": ["air"],
  "kind": "emission",
  "amount": 0.8,
  "unit": "kilogram",
  "characterized_scores": [0.8, 0],
  "percentages": [84.6, 0]
}
```

The physical amount is returned once; characterized scores vary by impact
category.

### Stable occurrence identity

The current occurrence ID includes the category label and traversal-local
unique ID. Schema 4 needs a category-independent identity derived from the
unrolled producer path.

The identity must distinguish:

- the same activity reached through different parents;
- repeated input exchanges from one parent;
- cycles revisited at different depths; and
- different reference products or co-product edges.

Construct and test a canonical path key from:

- parent occurrence path;
- producer activity identity;
- product/reference-product identity;
- exchange identity or deterministic sibling ordinal; and
- depth/visit position where necessary.

Do not merge nodes solely by Brightway activity ID.

## Multi-Category Calculation Strategy

An impact cutoff is category-specific. A node below the climate cutoff may be
important for toxicity. The engine must not build a climate-only topology and
claim it is complete for all categories.

### Initial implementation

1. Calculate all LCIA totals using the existing single factorized LCA.
2. Skip zero-total categories.
3. Run the existing occurrence traversal for each requested category.
4. Convert each traversal to an intermediate category graph.
5. Assign deterministic category-independent occurrence path keys.
6. Merge nodes, edges, and flows into the union bundle.
7. Store category membership and score arrays.
8. Stop cleanly when a total-request budget is reached.

This reduces transfer duplication but does not automatically remove
per-category traversal time.

### Optimization investigation

If all-nonzero traversal is too slow, investigate a multi-category scorer that:

- reuses the already-factorized technosphere matrix;
- computes cumulative scores for candidate products across multiple
  characterization score rows;
- batches product demands;
- prioritizes candidates by the maximum normalized absolute contribution across
  requested categories; and
- produces the union directly.

Do not implement custom multi-category traversal until the simpler merge is
numerically compared with independent Brightway traversals.

## Limits and Partial Results

Add explicit total and per-category budgets:

- `max_calculations_per_category`;
- `max_total_calculations`;
- `max_depth`;
- `max_union_nodes`;
- `max_flow_records`; and
- optional maximum graph-generation wall time.

Return partial results rather than failing the entire LCA.

Each category reports:

- status;
- coverage;
- unexpanded score;
- calculation count;
- included node/edge/flow counts;
- omitted flow count;
- omitted flow score; and
- truncation reasons.

If the emission-record limit is reached:

- retain complete process direct scores;
- retain aggregate signed score for omitted emissions;
- return an "other emissions" summary suitable for local display; and
- do not require a later detail request.

The default emission-record limit should be above the expected 1,500-record
case, for example 5,000.

## Compression

Enable gzip or Brotli for large REST JSON.

The current deployment did not return `Content-Encoding` when a client
advertised gzip. The measured 1.45 MB graph compressed to 177 KB, so compression
is part of the design, not an optional deployment tweak.

Compression may be configured in Traefik or application middleware. Verify that
MCP streaming endpoints are not buffered or broken.

## Calculate and Preview Workflow

### Remove the required Preview step

The webapp should not require this sequence:

```text
Choose/edit YAML
→ Preview Graph
→ Calculate LCA
```

The Calculate button should:

1. parse and validate the current YAML;
2. atomically apply that valid YAML as the current product graph;
3. update the lightweight foreground preview locally;
4. submit the same captured YAML and result options to `run_lca`;
5. mark results current only if the applied revision still matches; and
6. populate every result view from the single response.

This permits the simpler workflow:

```text
Choose/edit YAML
→ Calculate LCA
```

The separate Preview button can be removed or retained only as an optional
local visualization action. Preview must never be a prerequisite for
calculation.

### Do not calculate immediately on every keystroke

Removing required Preview does not imply sending `run_lca` on every YAML edit.
Immediate automatic calculation is unsafe with the current architecture:

- YAML is frequently invalid while the user is typing;
- background calculations currently take longer than three seconds;
- each category traversal adds work;
- `_calculation_lock` serializes calculations in one engine process;
- aborting the browser request does not necessarily cancel Brightway work; and
- rapid edits could queue obsolete calculations and cause 503/timeouts.

Recommended editing behavior:

```text
YAML edit
→ parse locally
→ if valid, update the local foreground preview
→ mark LCA results stale
→ wait for explicit Calculate
```

An optional auto-calculate mode can be considered later, but it requires:

- a substantial debounce, initially 1–2 seconds after valid input becomes
  stable;
- cancellation that reaches the server calculation rather than only aborting
  fetch;
- request revision/idempotency keys;
- suppression of obsolete queued calculations;
- rate limiting;
- a clear calculating/stale state; and
- production evidence that latency and concurrency budgets are met.

Selecting a bundled case study could optionally calculate automatically because
the YAML arrives as one valid document, but this should be a deliberate product
setting, not the default behavior for text editing.

## Latency Targets

The shared response optimization primarily eliminates later round trips and
reduces duplicated transfer. It does not guarantee a three-second initial
calculation, especially when scoring 25 categories.

Current evidence:

- Simple Mock graph: approximately 0.46 seconds locally.
- BAFU climate graph at 1% cutoff: approximately 4.1 seconds locally.
- BAFU climate graph at 0.1% cutoff: approximately 6.4 seconds locally.
- BAFU climate graph near 1,000 nodes: approximately 8.7 seconds locally.

These timings cover one detailed category. All-category traversal can take much
longer unless the engine receives additional multi-category optimization.

Use separate service-level targets:

| Case | Initial target |
|---|---:|
| Foreground-only calculation | ≤ 3 seconds |
| Simple/mock background | ≤ 3 seconds |
| BAFU with one bounded category | ≤ 10 seconds |
| BAFU all-nonzero bundle | Benchmark before committing; initial ceiling 20 seconds |
| Local branch expansion after response | ≤ 100 milliseconds |

If a strict three-second target is required for bundled BAFU cases, add
precomputation or a cache keyed by:

- canonical product YAML hash;
- result options;
- engine version;
- Brightway project/database fingerprint; and
- LCIA method data version.

Custom YAML cannot rely on a precomputed result.

## Engine Implementation Phases

### Phase 0: benchmark and contract fixtures

- Add a repeatable benchmark command.
- Record LCIA-only and graph-enabled runtime separately.
- Record compact and compressed sizes.
- Add 1,000-node and 1,500-flow synthetic serialization fixtures.
- Preserve the current independent category graphs as numerical references.

### Phase 1: eager graphs in the existing schema

- Add `result_options` to Python, MCP, and REST APIs.
- Add `explicit` and `all_nonzero` modes.
- Detect background providers and skip traversal for foreground-only graphs.
- Add total-request budgets and truncation reasons.
- Return every requested graph in the original response.
- Enable transport compression.

This phase enables the one-request frontend without waiting for schema 4.

### Phase 2: webapp one-button calculation

- Allow Calculate to validate and apply the current YAML directly.
- Remove Preview as a required state transition.
- Remove every view-triggered `calculateLca` call.
- Keep returned graphs in one result store.
- Expand branches and rows locally.
- Render only a collapsed visible subgraph.
- Virtualize large emission tables.

### Phase 3: shared schema-version-4 bundle

- Add category-independent occurrence path identities.
- Merge per-category nodes, edges, and flows.
- Return category-indexed score arrays.
- Update result models and API discovery.
- Migrate frontend consumers.
- Retain schema 3 compatibility during rollout.

### Phase 4: multi-category calculation optimization

- Profile traversal and solver time by category.
- Evaluate shared/batched scoring across method characterization rows.
- Compare union results with independent category traversals.
- Add safe caching for bundled/static inputs if needed.
- Revisit auto-calculation only after latency and cancellation work is complete.

## Tests

### Numerical correctness

- Every category total remains unchanged.
- Each category's included direct scores plus residual reconcile to its total.
- Each included node reconciles direct + included child cumulative +
  unexpanded to cumulative.
- Negative contributions preserve signs.
- Cumulative scores are never treated as additive exclusive contributions.
- Zero-total categories are represented without percentages.

### Union identity

- The same physical occurrence across categories has one union node.
- The same activity on different paths has different occurrence nodes.
- Repeated exchanges from one parent remain distinct.
- Cyclic visits remain distinct and bounded.
- Category membership selects the same nodes and edges as the independent
  category traversal.

### Limits

- Per-category and total calculation limits are enforced.
- Union-node and flow-record limits are enforced.
- Partial categories report accurate residual and truncation reasons.
- A 1,500-flow result is returned without a follow-up detail request.

### Lifecycle

- One root `bc.LCA` is constructed per `run_lca`.
- One inventory factorization is used.
- Temporary foreground databases are removed after success and failure.
- Foreground-only graphs do not trigger recursive traversal.

### Transport

- API discovery exposes result options and schema 4.
- REST responses negotiate compression.
- MCP transport remains operational.
- Results contain only finite JSON numbers.

### Webapp integration

- Choosing valid YAML and pressing Calculate works without Preview.
- Exactly one `POST /api/lca/run` occurs for one Calculate action.
- Opening every graph, category, process, and flow makes zero LCA requests.
- Editing YAML updates the local preview and marks results stale.
- Editing YAML does not automatically queue engine calls by default.
- Stale results cannot overwrite a newer YAML revision.
- A 1,000-node result renders a small initial subset.
- A 1,500-flow result remains responsive through local virtualization.

## Acceptance Criteria

1. A background-linked `run_lca` can return the complete configured bounded
   graph data in its original response.
2. Nodes expose direct, cumulative, and unexpanded scores for every included
   impact category.
3. Up to 1,500 included emission records can be returned without a detail
   endpoint.
4. Shared topology avoids repeating identical node/edge metadata for each
   category.
5. Global budgets prevent an unbounded union across 25 categories.
6. Compression is active for REST JSON.
7. The webapp can calculate valid YAML without first pressing Preview.
8. Result exploration performs no additional LCA calls.
9. Automatic calculation on text edits remains disabled until cancellation,
   concurrency, and latency requirements are implemented.
10. Foreground/simple cases meet the three-second target; larger BAFU cases use
    measured, explicit latency targets and honest progress states.

