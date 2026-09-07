# Plan: Searchable, Branchable LCA Scenario Analysis

Status: Proposed
Date: September 7, 2026

Related documents:

- [LCA database types and lifecycle](../docs/database_lifecycle.md)
- [Searching the LCA Background Database](../docs/searchable_background_database.md)
- [Proposed UI: Interactive LCA Scenario Explorer](proposed_interactive_lca_scenario_ui.md)
- [Two-Stage LCA with Eager Background Topology](PLAN_two_stage_lca_background_topology.md)

## Objective

Build an LLM-assisted scenario-analysis workflow that can:

1. inspect an existing foreground product graph;
2. identify foreground exchanges worth changing;
3. search `search.sqlite3` for plausible alternative background providers;
4. explain and validate each proposed substitution;
5. save alternatives as durable, branchable scenarios;
6. recalculate exact LCI and LCIA results with Brightway; and
7. compare scenarios while preserving their assumptions, evidence, and
   lineage.

The workflow should help answer questions such as:

- What lower-impact electricity providers could represent this process?
- What regional material datasets could replace the current global provider?
- Is there a recycled, renewable, or alternative-technology provider with a
  compatible reference product and unit?
- Which foreground substitutions reduce climate impact without causing large
  increases in water use, toxicity, or resource use?
- Which alternatives are promising but require engineering or procurement
  validation?

The system discovers possibilities; it does not claim that a database record
is technically, economically, or functionally interchangeable merely because
its name is similar or its calculated impact is lower.

## Core architectural decision

Use each data store for one responsibility:

```text
search/search.sqlite3
    shared, disposable background-inventory projection
    used to discover and inspect candidate providers
                    |
                    v
LLM + deterministic candidate validator
    proposes substitutions and records evidence
                    |
                    v
DoltLite scenario-model database
    durable foreground definitions, branches, commits, and lineage
                    |
                    v
canonical product-graph YAML
    calculation interchange format
                    |
                    v
temporary Brightway foreground_request_<uuid>
    exact LCI/LCIA calculation; deleted after request
                    |
                    v
scenario result store
    scores, deltas, result identity, and calculation provenance
```

Do not branch Brightway's internal `lci/databases.db`. Do not store foreground
scenarios in `search.sqlite3`. Both would couple durable user intent to
operational or derived storage.

## Terminology

- **Baseline**: the accepted foreground model against which alternatives are
  compared.
- **Scenario**: one complete, runnable foreground model with a fixed
  functional unit and explicit assumptions.
- **Scenario branch**: a named DoltLite branch containing one or more scenario
  commits derived from a baseline.
- **Target exchange**: the foreground input selected for possible replacement
  or parameter change.
- **Candidate provider**: a background activity found in `search.sqlite3` that
  may satisfy a target exchange.
- **Substitution**: replacement of one foreground-to-background provider link
  with another provider, with an explicit amount and unit conversion.
- **Feasible**: approved against stated technical constraints. A lower LCIA
  score alone never establishes feasibility.

## Scope

### Initial scope

- One-for-one substitution of background providers on existing foreground
  technosphere exchanges.
- Changes to foreground exchange amounts where an explicit rule or range is
  supplied.
- A fixed functional unit across baseline and scenarios.
- Exact recalculation of all LCIA categories configured in the product graph.
- Search across activity identity, reference product, name, location, unit,
  categories, classifications, synonyms, comments, and direct exchanges.
- Branch, commit, diff, compare, merge, and archive operations for scenario
  definitions.
- Human review before a generated candidate becomes an accepted scenario.

### Later scope

- Multiple coordinated substitutions in one scenario.
- Parameter sweeps and constrained optimization.
- Foreground process insertion, deletion, and route replacement.
- Supplier availability, price, performance, and procurement constraints from
  external systems.
- Uncertainty propagation and Monte Carlo comparisons.
- Portfolio-level optimization across several products.

### Out of scope for the first release

- Treating text similarity as proof of functional equivalence.
- Automatically changing the functional unit.
- Comparing scenarios calculated with different LCIA methods as if their
  category values were directly interchangeable.
- Writing candidate or scenario rows into `search.sqlite3`.
- Persisting request-specific `foreground_request_<uuid>` databases.
- Allowing the LLM to invent Brightway activity codes, units, amounts, or
  impact scores.

## User workflow

```text
Choose baseline
      |
      v
Calculate and identify target exchanges/hotspots
      |
      v
Search for alternatives in search.sqlite3
      |
      v
Inspect identity, unit, location, and direct recipe
      |
      v
Rank candidates and explain uncertainties
      |
      v
Create scenario branch and apply one candidate
      |
      v
Validate complete product graph
      |
      v
Run exact Brightway LCA
      |
      v
Compare baseline and scenario across all selected categories
      |
      v
Reject, revise, retain as experimental, or approve
```

## Stage 1: Establish a reproducible baseline

The user selects a bundled product graph, uploads YAML, or opens a saved
scenario commit. The system must:

1. parse and validate the product graph;
2. canonicalize it using the same normalization used for `result_id`;
3. record its functional unit, LCIA method, selected categories, and every
   foreground/background link;
4. run `run_lca_base` for exact baseline results;
5. optionally request contribution graphs for hotspot analysis; and
6. save the baseline model and calculation provenance.

Baseline provenance should include:

- canonical product-graph hash;
- DoltLite commit hash, if saved;
- Brightway project name;
- background database names and fingerprints;
- LCIA method and category tuples;
- engine and result-schema versions;
- calculation timestamp; and
- exact scores and units.

A scenario is comparable with its baseline only when compatibility checks
confirm the same functional unit, LCIA method/category definitions, and
appropriate background database lineage.

## Stage 2: Select target foreground exchanges

Targets can come from three sources:

### User-selected target

The user selects a foreground input such as electricity, material, transport,
fuel, or waste treatment.

### Hotspot-selected target

The system uses `process_contributions`, `background_link_intensities`, or a
requested contribution graph to identify foreground-to-background links with
large cumulative impact in one or more categories.

### Goal-selected target

The user states a goal such as:

> Find lower-climate-impact electricity alternatives without increasing water
> use by more than 10 percent.

The LLM translates the goal into explicit target exchanges, objective
categories, guardrail categories, geography, acceptable technologies, and
candidate limits. The user can inspect these constraints before scenario
generation.

Each target record must retain its product/process indices from the canonical
YAML so a substitution modifies exactly one exchange.

## Stage 3: Discover background candidates

Candidate generation should combine multiple deterministic searches rather
than rely on one free-text query.

### Search sequence

1. Read the current provider's exact activity identity.
2. Extract its reference product, unit, location, categories,
   classifications, synonyms, and direct recipe.
3. Search exact and normalized reference-product terms.
4. Search useful synonyms and technology terms.
5. Search locations allowed by the scenario constraints.
6. Search classifications when available.
7. Inspect direct exchanges for the strongest candidates.
8. Deduplicate by `(database, code)`.

Use `search_database` for broad discovery, `query_lca_database` for structured
filters and comparisons, and `get_lca_activity_inputs` for direct-recipe
inspection.

### Candidate query examples

Find activities with a compatible reference product and unit:

```sql
SELECT database, code, name, reference_product, location, unit
FROM activities
WHERE database = 'bafu'
  AND unit = :required_unit
  AND reference_product LIKE :product_pattern
ORDER BY location, name
```

Find technology or classification alternatives:

```sql
SELECT DISTINCT a.database, a.code, a.name, a.reference_product,
       a.location, a.unit, c.system, c.value
FROM activities AS a
JOIN activity_classifications AS c
  ON c.database = a.database AND c.code = a.code
WHERE a.unit = :required_unit
  AND c.value LIKE :classification_pattern
ORDER BY a.name, a.location
```

Compare direct input composition:

```sql
SELECT output_code, exchange_type, input_name, input_location, amount, unit
FROM exchange_details
WHERE output_database = :database
  AND output_code IN (:candidate_codes)
ORDER BY output_code, exchange_type, input_name
```

The MCP SQL interface will need parameterized query support or a dedicated
candidate-search tool before accepting arbitrary LLM-generated values. Do not
construct SQL through string interpolation in application code.

## Stage 4: Validate and rank candidates

Candidate selection has two separate outputs:

1. deterministic compatibility findings; and
2. an LLM explanation of relevance, assumptions, and uncertainty.

The LLM must not override a failed hard constraint.

### Hard validation rules

A candidate is rejected or held for explicit conversion when:

- its `(database, code)` does not exist in the fresh projection and Brightway;
- its activity type cannot supply the target exchange;
- its reference product is absent or demonstrably incompatible;
- its unit differs and no approved dimensional conversion exists;
- its location violates a required geography;
- it creates a forbidden modeling boundary or technology; or
- the resulting product graph fails normal engine validation.

Unit strings alone are insufficient. The first release should permit only
identical units or conversions from a reviewed conversion registry.

### Soft ranking signals

Rank remaining candidates using transparent component scores:

- reference-product similarity;
- activity-name and synonym similarity;
- exact unit match;
- geographic preference;
- classification similarity;
- technology preference;
- direct-recipe similarity or difference;
- data quality and representativeness metadata, where available; and
- user-stated inclusion or exclusion terms.

Do not include LCIA performance in the initial semantic compatibility score.
First decide whether a candidate is a plausible model; then calculate its
environmental consequences.

Every ranked candidate should expose a reason record such as:

```json
{
  "database": "bafu",
  "code": "exact-brightway-code",
  "compatibility": "review_required",
  "signals": {
    "reference_product": "exact",
    "unit": "exact",
    "location": "preferred",
    "classification": "related",
    "recipe": "materially different"
  },
  "warnings": [
    "Technology differs from the baseline provider",
    "Functional equivalence requires engineering review"
  ],
  "evidence_queries": ["candidate-search:...", "activity-inputs:..."]
}
```

## Stage 5: Create a branchable scenario

Use a dedicated DoltLite database as the durable scenario source of truth.
The database should store normalized model records and be able to reproduce
the canonical product-graph YAML exactly.

### Proposed minimum schema

```sql
CREATE TABLE models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE model_revisions (
    revision_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    parent_revision_id TEXT,
    canonical_yaml TEXT NOT NULL,
    product_graph_hash TEXT NOT NULL,
    functional_unit_json TEXT NOT NULL,
    lcia_config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);

CREATE TABLE scenario_changes (
    change_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL,
    process_index INTEGER NOT NULL,
    input_index INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    rationale TEXT,
    confidence TEXT NOT NULL,
    review_status TEXT NOT NULL,
    FOREIGN KEY (revision_id) REFERENCES model_revisions(revision_id)
);

CREATE TABLE candidate_evidence (
    evidence_id TEXT PRIMARY KEY,
    change_id TEXT NOT NULL,
    candidate_database TEXT NOT NULL,
    candidate_code TEXT NOT NULL,
    projection_fingerprint TEXT NOT NULL,
    compatibility_json TEXT NOT NULL,
    search_trace_json TEXT NOT NULL,
    FOREIGN KEY (change_id) REFERENCES scenario_changes(change_id)
);

CREATE TABLE calculation_runs (
    run_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    engine_version TEXT,
    result_schema_version INTEGER NOT NULL,
    background_fingerprint TEXT NOT NULL,
    method_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    FOREIGN KEY (revision_id) REFERENCES model_revisions(revision_id)
);
```

Large contribution graphs may eventually move to object storage with a hash
and URI in `calculation_runs`. The first implementation can retain complete
JSON while datasets remain small.

### Branch semantics

Recommended branch names:

```text
main
scenario/electricity-ch
scenario/recycled-polymer
scenario/rail-freight
```

One branch can contain iterative commits, but each commit must remain either:

- a valid runnable product graph; or
- explicitly marked `draft` and excluded from comparison.

Commit messages should identify the modeling decision rather than the tool
operation:

```text
Replace GLO grid mix with Swiss medium-voltage electricity
```

The DoltLite commit hash, normalized model revision, and product-graph hash
must be linked. DoltLite branch state alone is not a calculation identifier.

## Stage 6: Recalculate exact results

For each valid scenario revision:

1. serialize the normalized records to canonical product-graph YAML;
2. call `run_lca_base`;
3. verify that the returned `result_id` matches the submitted normalized
   graph;
4. save all configured LCIA totals, inventory totals, direct contributions,
   scaling vector, and background-link intensities;
5. request contribution graphs only for categories needed by the comparison
   view; and
6. save result provenance and errors without mutating the scenario model.

Brightway remains the only source of calculated impact scores. Fast previews
may use existing background-link intensities, but every retained comparison
must identify whether it is `preview` or `exact`.

### Amount semantics for provider replacement

A provider substitution does not automatically preserve functional
equivalence. The system needs an explicit amount policy:

- `same_amount_same_unit`: retain the foreground exchange amount when the
  reference product and unit are equivalent;
- `converted_amount`: apply a reviewed dimensional conversion and record the
  factor;
- `parameter_rule`: calculate the amount from an explicit engineering rule;
  or
- `manual_amount`: require the user to provide and approve the amount.

The system must never silently copy an amount across incompatible units or
products.

## Stage 7: Compare scenarios

Comparisons keep the functional unit and category definitions fixed and show:

- absolute score by impact category;
- absolute and percentage delta from baseline;
- categories improved, worsened, or unchanged within tolerance;
- changed foreground exchanges;
- changed background providers and locations;
- top changed inventory flows;
- top changed direct and cumulative contributors;
- compatibility warnings and unresolved feasibility questions; and
- calculation and source-data provenance.

Example comparison:

```text
Scenario: Swiss electricity provider
Baseline: main@<commit>
Model change: P2 input 3, provider bafu:<old> -> bafu:<new>

Impact category        Baseline       Scenario          Delta
Climate change         ...            ...               -...%
Water use              ...            ...               +...%
Resource use           ...            ...               -...%

Status: environmentally promising; technical equivalence requires review
```

Avoid a single unqualified “best” score. Pareto views should highlight
non-dominated scenarios when objectives conflict. Any normalization or
weighting must be optional, named, versioned, and displayed alongside raw
category results.

## Proposed MCP/API capabilities

Reuse the current tools where possible and add narrow scenario-specific tools.

### Existing tools

- `search_database`
- `query_lca_database`
- `get_lca_activity_inputs`
- `get_lca_database_schema`
- `run_lca_base`
- `get_lca_contribution_graphs`
- `run_lca`

### Proposed tools

#### `find_provider_alternatives`

Input:

```json
{
  "product_graph": "...",
  "process_index": 0,
  "input_index": 1,
  "constraints": {
    "locations": ["CH", "RER", "GLO"],
    "required_unit": "kilogram",
    "include_terms": ["recycled"],
    "exclude_terms": [],
    "limit": 20
  }
}
```

Output includes exact identities, deterministic compatibility findings,
ranking components, warnings, and projection fingerprint. It does not return
invented impact estimates.

#### `validate_scenario_change`

Validates a proposed replacement against the target exchange, conversion
policy, current projection, and Brightway activity identity. Returns a patched
product graph only when hard checks pass.

#### `calculate_scenario_comparison`

Calculates baseline and candidate with one compatibility envelope and returns
structured deltas. It should deduplicate baseline work when a trusted exact
baseline result with matching provenance already exists.

#### Scenario repository tools

Expose branch and commit operations through service-level methods rather than
arbitrary LLM-generated Dolt SQL:

- `list_scenario_branches`
- `create_scenario_branch`
- `save_scenario_revision`
- `get_scenario_revision`
- `diff_scenario_revisions`
- `merge_scenario_branch`
- `list_scenario_runs`

Mutating tools require explicit model, branch, expected-head commit, and actor
identity. Expected-head checks prevent accidentally committing against a
branch that changed after discovery.

## LLM responsibilities and boundaries

The LLM may:

- translate a user goal into search terms and explicit constraints;
- choose among supported search strategies;
- summarize candidate metadata and direct recipes;
- explain tradeoffs and missing evidence;
- propose scenario changes; and
- narrate exact calculated comparisons.

Deterministic application code must:

- resolve exact database/code identities;
- enforce units and conversion rules;
- patch the intended process/input index;
- validate the complete product graph;
- calculate all impact scores;
- compute numerical deltas and Pareto membership;
- enforce branch concurrency and permissions; and
- persist provenance.

The LLM must clearly distinguish:

- “found in the database” from “functionally interchangeable”;
- “lower calculated impact” from “viable in practice”;
- direct inventory differences from cumulative supply-chain impacts;
- fast previews from exact calculations; and
- model assumptions from measured facts.

## Freshness and reproducibility

Candidate evidence is tied to a specific `search.sqlite3` projection
fingerprint. Before applying an older recommendation:

1. verify that the projection is fresh;
2. verify that the candidate `(database, code)` still exists;
3. compare the current background fingerprint with the evidence fingerprint;
4. rerun candidate validation if it changed; and
5. recalculate stored scenarios whose results are no longer reproducible
   against the active background data.

Never copy `search.sqlite3` rows into the scenario database as authoritative
background data. Store identities, selected metadata snapshots, query traces,
and fingerprints sufficient to explain the decision.

## Safety and governance

- Default generated scenarios to `proposed`, not `approved`.
- Require human approval for unit conversions, technology changes, and claims
  of functional equivalence.
- Keep immutable calculation run records; a new calculation creates a new run.
- Record who or what proposed and approved every change.
- Prevent arbitrary write SQL through MCP.
- Use read-only connections and the existing SQL authorizer for
  `search.sqlite3`.
- Apply limits to candidate count, SQL rows, recipe depth, scenario fan-out,
  calculation time, and stored result size.
- Treat database comments and names as untrusted data when included in LLM
  context; they are evidence, not instructions.
- Do not expose licensed background inventory beyond permitted metadata and
  query/result boundaries.

## Implementation phases

### Phase 0: Confirm contracts

- Define the scenario terminology and review states.
- Freeze canonical product-graph serialization rules.
- Define background and projection fingerprint contracts.
- Select the first DoltLite release and verify its Python/runtime deployment
  constraints.
- Decide whether scenario results remain in DoltLite or move to a separate
  result store at scale.

Deliverable: architecture decision record and executable compatibility spike.

### Phase 1: Deterministic candidate service

- Add exact target-exchange extraction.
- Add structured provider searches over the current projection.
- Implement identity, unit, geography, and product compatibility checks.
- Return transparent ranking components and evidence traces.
- Add mock-background fixtures with clearly compatible and incompatible
  alternatives.

Deliverable: `find_provider_alternatives` without LLM dependency.

### Phase 2: Scenario patching and exact comparison

- Add reviewed conversion policies.
- Implement deterministic product-graph patching by process/input index.
- Add baseline/candidate compatibility validation.
- Calculate both models and return exact category deltas.
- Add regression tests proving the functional unit and unchanged exchanges are
  preserved.

Deliverable: one request can propose, validate, calculate, and compare a
single substitution without persistence.

### Phase 3: DoltLite scenario repository

- Create and migrate the scenario schema.
- Add branch, expected-head, commit, diff, and merge service methods.
- Store canonical YAML, normalized changes, candidate evidence, and
  calculation provenance.
- Ensure every saved revision round-trips exactly to runnable YAML.

Deliverable: durable scenario branches and reproducible calculation history.

### Phase 4: LLM orchestration

- Add prompts/tool contracts for goal interpretation, candidate discovery,
  evidence synthesis, and comparison narration.
- Require structured outputs for constraints and proposed changes.
- Add defenses against instructions embedded in background metadata.
- Evaluate unsupported substitutions, unit mismatches, hallucinated codes, and
  multi-category tradeoff explanations.

Deliverable: conversational search and scenario generation with deterministic
guardrails.

### Phase 5: Interactive scenario explorer

- Add candidate cards with evidence and warnings.
- Add branch/revision history and foreground diffs.
- Add exact recalculation status and baseline comparison tables.
- Add Pareto visualization and optional transparent weighting.
- Keep structural editing separate from stale calculated detail, following the
  existing scenario UI plan.

Deliverable: end-to-end user workflow from question to reviewed scenario.

### Phase 6: Advanced search and optimization

- Add embeddings or hybrid retrieval only after measuring lexical/structured
  search recall.
- Support multi-change scenario generation with a bounded search budget.
- Add parameter sweeps, constraints, uncertainty, and optimization.
- Add external feasibility evidence such as cost, performance, and supplier
  availability through separately governed connectors.

Deliverable: constrained exploration beyond one-for-one substitutions.

## Testing strategy

### Unit tests

- Target exchange resolution is stable by process/input index.
- Search filters are parameterized and bounded.
- Exact identity and unit checks cannot be bypassed by LLM output.
- Product-graph patching changes only the intended fields.
- Canonical YAML round-trips through the scenario schema.
- Scenario deltas use matching categories and units.
- Fingerprint changes invalidate stale evidence and results.

### Integration tests

- Build candidates from `mock_background`, create a branch, calculate it, and
  compare it with the baseline.
- Verify temporary Brightway foreground databases are removed after successful
  and failed scenario calculations.
- Verify scenario branches do not alter `search.sqlite3` or shared Brightway
  background data.
- Verify two writers receive a clear expected-head conflict instead of losing
  changes.
- Verify branch checkout produces the expected canonical YAML and `result_id`.

### LLM evaluations

- Finds a valid regional provider when one exists.
- Says no compatible candidate was found when appropriate.
- Does not invent activity codes or scores.
- Rejects or escalates incompatible units.
- Separates semantic compatibility from environmental performance.
- Reports impact-category tradeoffs instead of optimizing only climate change.
- Preserves the functional unit and unchanged exchanges.
- Treats malicious database text as data, not instructions.

### Performance tests

- Candidate discovery latency at 5, 20, and 100 result limits.
- Recipe-comparison cost for increasing candidate counts.
- Baseline reuse versus full recalculation.
- Parallel scenario calculations under the engine's serialization lock.
- DoltLite branch, commit, diff, and merge latency as history grows.

## Acceptance criteria for the first production slice

Use a product graph with one foreground process and at least three background
inputs. The system must:

1. calculate and save an exact baseline;
2. identify one target foreground input;
3. return at least one valid and one rejected candidate from the mock fixture;
4. explain each compatibility decision using stored projection evidence;
5. create a scenario branch and commit one accepted substitution;
6. prove that only the selected exchange changed;
7. recalculate all configured impact categories;
8. display absolute and percentage deltas with score units;
9. retain the same functional unit;
10. preserve the branch commit, product-graph hash, background fingerprint,
    and exact result;
11. reproduce the result from the saved branch while source fingerprints are
    unchanged; and
12. leave no temporary foreground database after completion.

## Open decisions

1. Should the initial scenario repository store only canonical YAML plus
   changes, or also maintain fully normalized process/exchange tables?
2. Which unit library and reviewed conversion registry should be authoritative?
3. Which location fallback rules are scientifically acceptable by material or
   service class?
4. Should candidate recipe similarity be a ranking signal in the first release
   or displayed only as evidence?
5. Which data-quality metadata from BAFU can be exposed and compared reliably?
6. How should stale historical results be displayed after background data or
   LCIA methods change?
7. What approval roles are required before a scenario can be labeled viable?
8. Should exact results live in DoltLite, or should DoltLite retain only their
   hashes and references to immutable object storage?

## Recommended first vertical slice

Start with the bundled mock plastic broom and a purpose-built set of mock
alternative providers. Implement one background-provider substitution at a
time:

```text
baseline broom
    -> select polypropylene input
    -> search compatible mock alternatives
    -> reject a deliberately incompatible unit/product
    -> branch accepted alternative
    -> run exact EF climate-change calculation
    -> compare and persist result
```

After the workflow is deterministic and well tested, run the same slice on a
BAFU-linked material or electricity exchange. This separates scenario-system
correctness from the scientific review required for real-provider
substitutions.
