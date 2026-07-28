# Plan: Two-Stage LCA with Eager Background Topology

Status: Proposed  
Date: July 28, 2026  
Related plan:
[`PLAN_eager_background_graph_bundle.md`](PLAN_eager_background_graph_bundle.md)

## Decision Summary

Split calculation into two stateless requests.

### Stage 1: immediate base LCA and physical background topology

Run as soon as the webapp submits one complete, valid YAML revision.

Return:

- aggregated inventory;
- LCIA totals for the categories resolved from the YAML;
- foreground and background activity-level direct results;
- the foreground graph;
- direct background-provider roots; and
- one bounded, category-independent background activity graph containing the
  activities, products, technosphere exchanges, and optionally direct
  biosphere exchanges needed for local upstream exploration.

The webapp can expand the returned physical background graph locally without
calling the activity database for each click.

### Stage 2: contribution overlays

After Stage 1 renders, make a second request for the selected contribution
category or small category set.

The first implementation remains stateless: Stage 2 repeats the base LCA and
then runs the existing Brightway contribution traversal. It returns
occurrence-specific direct, cumulative, and unexpanded scores that reference
the physical activities and exchanges already returned by Stage 1.

The same Stage 2 graph supplies both the Contribution Tree and the recursive
impact-oriented Sankey. No polling or server-side calculation session is
required.

## Why Stage 1 Must Not Use the Existing Impact Cutoff

The existing contribution cutoff means:

```text
absolute cumulative branch score
---------------------------------  >= impact cutoff
absolute total category score
```

That cutoff cannot define the Stage 1 physical topology without doing the
category-specific contribution work Stage 1 is intended to defer.

It is also not category-independent. A branch below the climate-change cutoff
can exceed the toxicity, water-use, or resource-depletion cutoff.

Physical exchange amounts are not a safe universal alternative cutoff. The
background graph mixes kilograms, kilowatt hours, tonne-kilometres, cubic
metres, and other units. Comparing their raw magnitudes would silently prefer
some units over others.

Stage 1 therefore uses **topology limits**, not an impact cutoff:

- maximum background depth;
- maximum unique activities;
- maximum technosphere exchanges;
- maximum direct biosphere records;
- a deterministic serialized-size budget; and
- an emergency wall-time budget.

Stage 2 continues to use the existing category-relative impact and biosphere
cutoffs.

## Recommended Initial Topology Limits

Use these only as provisional benchmark settings:

```yaml
background_topology:
  max_depth: 6
  max_activities: 2500
  max_exchanges: 10000
  max_biosphere_records: 5000
  max_raw_bytes: 5000000
  max_build_seconds: 1.0
  include_biosphere: true
```

The final defaults must be selected from measured depth-growth curves for
every mock and BAFU example.

### Why start with depth 6

- It permits several useful upstream expansion clicks from each direct
  provider.
- Deduplicating activities prevents cycles from recursively multiplying the
  transfer size.
- It is bounded enough to benchmark before committing to the existing
  contribution-plan depth of 12.

Depth is counted from a direct background provider:

```text
depth 0: direct provider named by the foreground YAML
depth 1: that provider's direct technosphere inputs
depth 2: their inputs
...
```

### Limit precedence

Traversal is deterministic breadth-first traversal from the direct providers.
Within one depth, activities and exchanges are sorted by stable database/code
identity.

An activity expansion is atomic: either all of its direct exchange records are
included, or it remains a frontier node. Do not serialize half of one
activity's inputs merely because a record limit was reached.

Limits are applied in this order:

1. `max_depth`;
2. `max_activities`;
3. `max_exchanges`;
4. `max_biosphere_records`;
5. `max_raw_bytes`; and
6. `max_build_seconds` as an emergency safety stop.

The count and byte limits produce deterministic results. Wall time is only a
safety mechanism and must report that it caused truncation.

### Numerical filtering

Only exact zero exchanges and values within the engine's numerical-noise
tolerance may be omitted automatically. This is not presented as an impact or
coverage cutoff.

## Stage 1 Calculation

### Trigger

The webapp starts Stage 1 exactly once for a submitted valid YAML revision:

```text
select/upload/submit complete YAML
→ parse and validate
→ calculate Stage 1
```

Typing through temporarily valid intermediate editor states must not
automatically queue calculations. The client calculates a canonical YAML hash
and deduplicates repeated submissions of the same revision.

### LCIA category resolution

Separate total-score selection from contribution-graph selection.

Recommended YAML:

```yaml
lcia:
  method_name: "EF v3.1"
  categories:
    - climate change
    - acidification
  contribution_graph:
    categories:
      - climate change
```

Semantics:

- `lcia.categories`, when present, selects totals and direct activity scores
  returned by Stage 1.
- Omitting `lcia.categories` preserves current behavior and calculates every
  category in the method family.
- `lcia.contribution_graph.categories` remains the default Stage 2 category
  selection.
- A Stage 2 request can override the default category selection without
  changing the YAML revision.

### Physical topology construction

Start with every resolved background provider referenced directly by a
foreground input.

For each unique background activity:

1. assign a stable ID from database and code;
2. return name, location, unit, reference product, and reference-production
   amount;
3. return its aggregate solved supply amount when it is present in the LCI
   solution;
4. return every bounded technosphere input exchange;
5. return signed amounts and product identities without impact filtering;
6. optionally return bounded direct biosphere exchanges; and
7. enqueue an unseen technosphere provider until a topology limit is reached.

The activity graph is cyclic. Each activity is serialized once, while multiple
physical exchange edges may point to it. Cyclic edges point to the existing
activity and do not enqueue it again.

### Activity-level direct results

The regular Brightway calculation already exposes:

```text
supply_array
inventory
characterized_inventory
```

Use these to return:

- aggregate supply by unique activity;
- direct inventory records by activity; and
- direct LCIA score arrays by activity for the Stage 1 categories.

These are activity-level aggregates. They are not occurrence-tree cumulative
scores.

## Proposed Stage 1 Contract

Request:

```json
{
  "product_graph": "...",
  "result_options": {
    "stage": "base",
    "background_topology": {
      "max_depth": 6,
      "max_activities": 2500,
      "max_exchanges": 10000,
      "max_biosphere_records": 5000,
      "max_raw_bytes": 5000000,
      "max_build_seconds": 1.0,
      "include_biosphere": true
    }
  }
}
```

Response outline:

```json
{
  "calculation_revision": "sha256:canonical-yaml",
  "inventory": [],
  "impact_categories": [],
  "activity_results": [],
  "foreground_graph": {},
  "background_activity_graph": {
    "roots": ["background-activity:bafu:..."],
    "activities": [
      {
        "id": "background-activity:bafu:...",
        "database": "bafu",
        "code": "...",
        "name": "Polylactide, granulate, at plant",
        "location": "GLO",
        "unit": "kilogram",
        "reference_product": "polylactide",
        "reference_production_amount": 1.0,
        "aggregate_supply_amount": 0.52,
        "direct_scores": [0.2, 0.001],
        "depth": 0,
        "frontier": false
      }
    ],
    "exchanges": [
      {
        "id": "background-exchange:...",
        "consumer_activity_id": "background-activity:bafu:...",
        "producer_activity_id": "background-activity:bafu:...",
        "product_id": "background-product:bafu:...",
        "amount_per_consumer_reference_unit": 2.4,
        "unit": "kilowatt hour"
      }
    ],
    "biosphere_records": [],
    "status": "partial",
    "truncation_reasons": ["max_depth"],
    "included_activity_count": 850,
    "included_exchange_count": 3100,
    "included_biosphere_record_count": 1400,
    "frontier_activity_count": 210
  }
}
```

The category table defines the positions in `direct_scores`; do not repeat
category IDs on every activity.

`aggregate_supply_amount` is the total matrix solution for one unique
activity. It must not be presented as the amount for each path occurrence.

## Local Background Exploration

The webapp stores Stage 1 activities and exchanges by stable ID.

When a user expands an activity:

1. read outgoing input exchanges from the local store;
2. create visible child rows or graph nodes;
3. reuse an existing activity record when multiple parents reference it;
4. label cycle edges explicitly;
5. stop at a frontier activity; and
6. make no `/api/database/activity-inputs` call for any included activity.

The activity graph view may show each unique activity once. A tree-style view
creates frontend occurrences for each parent path:

```text
activity: one database process
occurrence: one path-specific use of that activity
```

Stage 1 occurrences can show physical amounts and activity-level direct data.
They must not claim category-specific cumulative impact.

## Stage 2 Calculation

### Trigger

After Stage 1 is rendered, the webapp may:

- immediately request the YAML-configured default contribution category; or
- wait until the user opens the Contribution Tree or recursive Sankey.

Initially request one category. Do not automatically request all nonzero
categories.

### Stateless first implementation

Stage 2 sends the same captured YAML and its canonical revision:

```json
{
  "product_graph": "...",
  "base_revision": "sha256:canonical-yaml",
  "categories": [
    "climate change | global warming potential (GWP100)"
  ],
  "cutoff": 0.001,
  "biosphere_cutoff": 0.0001,
  "max_depth": 12,
  "max_calculations": 1000,
  "include_flows": true
}
```

The server repeats foreground setup, LCI, and LCIA, then invokes the current
independent Brightway traversal for the requested categories.

No polling is required. The second HTTP request remains open and returns when
the graph is complete.

### Stage 2 response

Return:

- the same `base_revision`;
- category status and coverage;
- occurrence parent/child relationships;
- stable references to Stage 1 activity and exchange IDs;
- path-specific supply amounts;
- direct, cumulative, and unexpanded scores;
- characterized elementary-flow scores; and
- activity aggregation across occurrences.

Avoid repeating Stage 1 names, locations, products, units, and physical
exchange metadata when a stable reference is sufficient.

The returned occurrence graph is retained in the browser and used by both the
Contribution Tree and the recursive impact Sankey.

## Webapp State and Request Ordering

Use separate state:

```text
baseStatus:  idle | calculating | complete | error
graphStatus: idle | calculating | complete | error
```

Required sequence:

```text
capture valid YAML and revision
→ await Stage 1
→ populate Inventory, Impact Analysis, Process Results, and physical graph
→ start Stage 2
→ show contribution loading state
→ populate Contribution Tree and recursive Sankey
```

Do not dispatch both requests simultaneously. The current engine serializes
calculations, but it does not provide a priority-aware FIFO queue, so the
graph-enabled request could otherwise run first.

If the YAML changes:

- mark both result stages stale;
- do not automatically calculate an intermediate editor revision;
- ignore a Stage 2 response whose `base_revision` no longer matches; and
- retain browser-cached data only under its canonical revision key.

## Performance Expectations

Phase 0 measured graph-disabled core runs:

| Case | LCIA-only core time |
|---|---:|
| Mock examples | approximately 0.16 seconds |
| BAFU examples | approximately 2.6–2.8 seconds |

The BAFU Plastic Broom measured:

```text
base inventory + all 25 EF totals:       2.76 seconds
one climate contribution traversal:      3.56 seconds
25 independent contribution traversals: 95.43 seconds
```

The Stage 1 topology overhead has not yet been measured. A strict three-second
Stage 1 target cannot be promised when the existing base measurement already
reaches 2.76 seconds on the benchmark machine.

Initial service targets:

| Work | Target |
|---|---:|
| Mock Stage 1 | <= 1 second |
| BAFU Stage 1 base calculation | <= 3 seconds |
| BAFU topology construction overhead | benchmark target <= 0.5 seconds |
| BAFU Stage 1 compressed response | benchmark target <= 1 MB |
| Local expansion within bundled topology | <= 100 milliseconds |
| Stage 2 one bounded category | <= 10 seconds |

If topology construction cannot meet the overhead target, reduce the default
depth or move direct biosphere records behind Stage 2 before introducing
server-side calculation sessions.

## Required Benchmark Before Selecting Defaults

Add a topology-only benchmark for every mock and BAFU YAML.

For depths 2, 4, 6, 8, and 12, record:

- topology construction time excluding the base LCA;
- total Stage 1 time;
- unique activity count;
- technosphere exchange count;
- biosphere record count;
- frontier activity count;
- cycle-edge count;
- compact JSON size;
- gzip size; and
- maximum and median branching factor.

Also record the overlap between the Stage 1 topology and each independent
Phase 0 contribution graph:

```text
contribution occurrence activity IDs
contained in Stage 1 topology
```

This overlap does not prove impact completeness, but it indicates whether the
provisional structural depth is useful for the existing contribution views.

Choose defaults by the deepest complete deterministic level that satisfies the
Stage 1 time and response budgets for the target BAFU examples. Do not choose
defaults from one climate graph alone.

## Engine Implementation Phases

### Phase A: topology benchmark

- Build a private category-independent topology walker.
- Measure depth-growth curves and response sizes.
- Select provisional deterministic limits.
- Do not change the public API.

### Phase B: Stage 1 engine contract

- Add explicit Stage 1 result options.
- Add optional `lcia.categories`.
- Return stable background activity, product, exchange, and flow identities.
- Return activity-level supply, direct inventory, and direct score arrays.
- Report frontier nodes and every truncation reason.
- Preserve current schema-3 behavior for existing callers.

### Phase C: Stage 2 stateless endpoint

- Add a contribution-only request accepting the captured YAML revision.
- Reuse the existing independent Brightway traversal.
- Reference Stage 1 physical IDs where possible.
- Return one selected category by default.
- Keep the endpoint synchronous; do not add polling or server sessions.

### Phase D: webapp integration

- Start Stage 1 for one submitted valid YAML revision.
- Render base views immediately.
- Expand bundled physical background topology locally.
- Start Stage 2 only after Stage 1 completes.
- Use one Stage 2 graph for both the tree and recursive Sankey.
- Suppress stale responses by canonical revision.

### Phase E: optional optimization

Only after measuring the two-call workflow:

- retain a live calculation job to avoid repeating the base LCA;
- add a scored-kernel cache;
- add multi-category union traversal; or
- add persistent graph caching.

These optimizations are not prerequisites for the two-stage webapp.

## Tests

### Stage 1 numerical correctness

- Inventory and LCIA totals remain unchanged.
- Activity direct scores reconcile to each category total within tolerance.
- Aggregate activity supply matches the Brightway supply array.
- Direct biosphere records reconcile to the activity inventory columns.
- Negative and substitution exchanges retain their signs.

### Stage 1 topology

- Direct YAML background providers are exactly the topology roots.
- Every exchange endpoint references a returned activity or explicit frontier
  identity.
- The same database activity is serialized once.
- Multiple parents can reference the same activity.
- Cycles produce edges without infinite expansion.
- Traversal order and IDs are deterministic.
- Expanding one activity never returns only part of its direct input set.
- Every limit produces an explicit truncation reason.
- Stage 1 never invokes `NewNodeEachVisitGraphTraversal`.

### Stage 2 contribution results

- Totals equal Stage 1 totals for the same revision and category.
- Independent occurrence graphs match the Phase 0 numerical references.
- Occurrences reference valid Stage 1 activity identities.
- Direct plus included children plus unexpanded reconciles to cumulative score.
- The same returned graph supports the tree and recursive Sankey.

### Webapp integration

- One submitted YAML starts Stage 1 exactly once.
- Inventory and impact views render before Stage 2 completes.
- Bundled background activities expand without database requests.
- Stage 2 begins only after Stage 1 returns.
- No polling occurs in the stateless implementation.
- A stale Stage 2 response cannot overwrite a newer revision.
- Opening the tree and Sankey does not issue duplicate graph calculations.

## Acceptance Criteria

1. A valid submitted YAML produces Inventory and Impact Analysis before any
   contribution graph is available.
2. The Stage 1 response contains a bounded physical background graph rooted at
   every direct background provider.
3. Users can repeatedly expand every included background activity locally
   without querying the activity database.
4. Stage 1 topology limits are structural and never presented as LCIA coverage.
5. Stage 2 returns category-specific occurrence contribution data through one
   ordinary request without polling.
6. The Stage 2 graph supplies both the Contribution Tree and recursive Sankey.
7. Both stages are tied to the same immutable canonical YAML revision.
8. Existing callers retain schema-3 behavior until they opt into the new
   two-stage contracts.
