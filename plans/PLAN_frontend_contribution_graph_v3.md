# Plan: Frontend Support for LCA Contribution Graphs

## Status

Proposed — implement after deploying backend commit `aa8667b`.

## Objective

Update the frontend for LCA result schema version 3 and render recursive
foreground and background contribution trees from the single response returned
by:

```text
POST /api/lca/run
```

The frontend must not make separate LCA requests for individual background
processes. The backend now traverses the connected product system using the
existing LCA object and returns the requested contribution graphs directly.

## Compatibility

The frontend must:

1. Accept `result_schema_version: 3`.
2. Add types for the new top-level `contribution_graphs` array.
3. Continue supporting results where `contribution_graphs` is absent or empty.
4. Retain the existing contribution display as a fallback when no graph was
   requested for the selected impact category.
5. Avoid assuming that `process_contributions` contains only foreground
   processes. For graph-enabled categories, it can now contain explicit
   background activities.

## Selecting a Contribution Graph

Each contribution graph belongs to one impact category. Match the selected
impact category against:

```text
contribution_graphs[n].label
```

If a matching graph exists, use it for the contribution-tree view. If no graph
exists, show the existing legacy contribution view or explain that recursive
contributions were not requested for that category.

Do not trigger another REST calculation when a graph is unavailable.

## Tree Structure

The functional-unit node is the root:

```json
{
  "kind": "functional_unit",
  "scope": null
}
```

Each process occurrence has a unique `node.id`. Use this ID as the rendered
tree-node identity.

The same underlying activity can appear more than once in the tree. These
occurrences have distinct `node.id` values but share the same `activity_id`.
Do not collapse repeated occurrences in the tree. Use `activity_id` only when
aggregating or linking to activity-level details.

## Edge Direction

Contribution graph edges preserve the physical producer-to-consumer direction:

```text
source / producer_id -> target / consumer_id
```

The visual contribution tree goes backward from the functional unit into its
upstream supply chain. Therefore, while building the tree, traverse edges in
the following direction:

```text
consumer_id -> producer_id
```

In other words, find edges whose `consumer_id` matches the current tree node,
then render their `producer_id` nodes as children.

## Impact Values

For each process occurrence, display:

- `direct_score`: impact occurring directly at this process occurrence;
- `cumulative_score`: direct impact plus the occurrence's upstream supply
  chain;
- `cumulative_percentage`: cumulative score divided by the category total;
- `supply_amount` and `unit`;
- `scope`: foreground or background; and
- `process_name` and location.

Do not add cumulative scores across nodes. Parent cumulative scores already
include their children, so adding them would double-count impact.

The additive summary is `activity_contributions`. It sums occurrence-level
`direct_score` values for each shared activity and includes
`occurrence_count`.

## Cutoff and Unexpanded Impact

Each node can contain `unexpanded_score`. This represents upstream impact that
was not expanded because of the configured impact cutoff, maximum depth, or
calculation limit.

Only render an artificial child such as:

```text
Unexpanded impact (cutoff/depth)
```

when `unexpanded_score` is materially nonzero. Use a numerical tolerance to
avoid displaying floating-point noise.

Do not render a generic "background residual." Background processes that were
visited are returned as explicit nodes. The unexpanded value represents only
the portion omitted by the traversal limits.

Use the graph-level fields as follows:

- `status: complete`: all category impact is represented by visited direct
  process scores;
- `status: partial`: some impact remains in `unexpanded_score`;
- `status: zero_total`: the category total is zero and percentages are
  unavailable;
- `coverage`: visited direct process impact divided by total impact; and
- `unexpanded_score`: total impact not represented by visited direct process
  scores.

## Elementary Flows

The optional `flows` array contains characterized elementary flows.

Attach each flow to its process occurrence using:

```text
flow.process_occurrence_id -> node.id
```

Render:

- extractions above the process; and
- emissions below the process.

Flow records also contain their characterized `score`, percentage, amount,
unit, name, categories, and `kind`.

## Suggested TypeScript Shape

```ts
type ContributionScope = "foreground" | "background";

interface ContributionGraphNode {
  id: string;
  kind: "functional_unit" | "process";
  activity_id: string | null;
  process_name: string;
  database: string | null;
  code: string | null;
  location: string | null;
  scope: ContributionScope | null;
  depth: number;
  supply_amount: number;
  unit: string;
  direct_score: number;
  cumulative_score: number;
  cumulative_percentage: number | null;
  unexpanded_score: number;
  terminal: boolean;
}

interface ContributionGraphEdge {
  id: string;
  source: string;
  target: string;
  consumer_id: string;
  producer_id: string;
  flow_name: string;
  amount: number;
  unit: string;
}

interface ContributionGraphFlow {
  id: string;
  process_occurrence_id: string;
  flow_name: string;
  categories: string[];
  kind: "extraction" | "emission";
  amount: number;
  unit: string;
  score: number;
  percentage: number | null;
}

interface ActivityContribution {
  activity_id: string;
  process_name: string;
  database: string;
  code: string;
  location: string | null;
  scope: ContributionScope;
  direct_score: number;
  percentage: number | null;
  occurrence_count: number;
}

interface ContributionGraph {
  id: string;
  label: string;
  unit: string;
  total_score: number;
  cutoff: number;
  biosphere_cutoff: number;
  max_depth: number | null;
  max_calculations: number;
  calculation_count: number;
  coverage: number | null;
  unexpanded_score: number;
  status: "complete" | "partial" | "zero_total";
  nodes: ContributionGraphNode[];
  edges: ContributionGraphEdge[];
  flows: ContributionGraphFlow[];
  activity_contributions: ActivityContribution[];
}
```

## Mock Plastic Broom Acceptance Test

Use the Mock Plastic Broom Climate Change graph as the initial frontend
regression fixture.

Expected tree occurrences:

```text
1 mock plastic broom
  -> Mock plastic broom assembly
    -> Mock polypropylene granulate, at plant
      -> Mock grid electricity, medium voltage
    -> Mock freight transport, small truck
      -> Mock grid electricity, medium voltage
```

The two grid nodes must remain separate occurrences even though they share one
underlying `activity_id`.

Expected Climate Change results:

| Item | Direct score | Cumulative score |
| --- | ---: | ---: |
| Complete product system | 0 | 0.9488709719424245 |
| Mock polypropylene | 0.5199999809265137 | 0.9359999718666074 |
| Grid through polypropylene | 0.41599999094009377 | 0.41599999094009377 |
| Mock freight transport | 0.009495000173449508 | 0.0128710000758171 |
| Grid through freight | 0.0033759999023675914 | 0.0033759999023675914 |

Expected graph-level values:

```text
status = complete
coverage = 1
unexpanded_score = 0
total_score = 0.9488709719424245 kg CO2-Eq
```

## Frontend Tests

Add tests for:

1. Accepting result schema version 3.
2. Falling back safely when `contribution_graphs` is empty.
3. Selecting a graph by exact impact-category label.
4. Building the tree using `consumer_id -> producer_id`.
5. Preserving two occurrences with the same `activity_id`.
6. Avoiding cumulative-score summation.
7. Showing unexpanded impact only when materially nonzero.
8. Attaching flows through `process_occurrence_id`.
9. Positioning extractions above activities and emissions below activities.
10. Handling `zero_total` graphs and null percentages.
11. Displaying explicit background rows in `process_contributions`.

## Definition of Done

- The frontend performs one `/api/lca/run` request for the product system.
- The Mock Plastic Broom contribution tree includes both grid occurrences.
- Background processes are shown explicitly.
- No generic background residual is displayed for a complete graph.
- Partial graphs clearly show their unexpanded impact.
- Direct and cumulative scores are labeled distinctly.
- Existing results without contribution graphs still render correctly.
- Frontend tests cover schema compatibility, traversal direction, repeated
  occurrences, flows, and cutoff behavior.
