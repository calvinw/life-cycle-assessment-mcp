# Scenario Analysis Walkthrough: Progress and Resume Point

Status: Paused after candidate validation  
Last updated: September 11, 2026

This document records the hands-on walkthrough of the workflow proposed in
[Plan: Searchable, Branchable LCA Scenario Analysis](../plans/PLAN_searchable_scenario_analysis.md).
For a conceptual overview, see
[Exploring Product-Graph Alternatives with SQLite and DoltLite](scenario_analysis_explainer.md).

## Goal of the exercise

Test the scenario-analysis workflow one stage at a time using fictional,
deterministic data before attempting a real BAFU provider substitution.

The selected experiment replaces the freight provider in the mock plastic
broom:

```text
Baseline provider:
  Mock freight transport, small truck

Candidate provider:
  Mock freight transport, small truck, direct emissions only
```

The systems retain separate responsibilities:

- `search/search.sqlite3` discovers candidate background activities;
- DoltLite will preserve versioned baseline and scenario product graphs;
- Brightway performs exact LCA calculations; and
- product-graph YAML remains the canonical calculation input.

## Activities in the test fixture

The product graph is
[`mock_examples/mock_plastic_broom.yaml`](../mock_examples/mock_plastic_broom.yaml).
It contains one foreground activity:

```text
Mock plastic broom assembly
```

The foreground activity consumes:

| Background input | Amount | Unit |
| --- | ---: | --- |
| Mock polypropylene granulate, at plant | 0.52 | kilogram |
| Mock freight transport, small truck | 0.1055 | ton kilometer |

The source fixture
[`mock_background/database.yaml`](../mock_background/database.yaml) contains
four background activities:

| Code | Activity | Reference product | Unit |
| --- | --- | --- | --- |
| `mock-grid-electricity` | Mock grid electricity, medium voltage | electricity, medium voltage | kilowatt hour |
| `mock-polypropylene` | Mock polypropylene granulate, at plant | polypropylene granulate | kilogram |
| `mock-small-truck` | Mock freight transport, small truck | freight transport | ton kilometer |
| `mock-small-truck-direct` | Mock freight transport, small truck, direct emissions only | freight transport | ton kilometer |

All four activities have location `MOCK`.

## Completed stage 1: Calculate the unchanged baseline

The local REST server was started on port `9000`. The unchanged mock broom was
submitted to:

```http
POST /api/lca/base
```

Baseline identity:

```text
Name: Mock Plastic Broom — 1 unit
Functional unit: 1.0 unit — 1 mock plastic broom
Method: EF v3.1
Result schema version: 3
Result ID: b4b84db7f14a1bb27467dfc2c480dec8979d47a968fcfeafecbc009e836b68d9
```

Exact baseline climate result:

```text
0.9488709719424245 kg CO2-Eq
```

Direct activity contributions reported for that category:

| Activity | Direct score (kg CO2-Eq) | Percentage |
| --- | ---: | ---: |
| Mock polypropylene granulate, at plant | 0.5199999809265137 | 54.80197% |
| Mock grid electricity, medium voltage | 0.41937599084246135 | 44.19737% |
| Mock freight transport, small truck | 0.009495000173449508 | 1.00066% |
| Mock plastic broom assembly | 0 | 0% |

This was only a baseline calculation. No candidate had been searched,
substituted, or calculated at this point.

## Completed stage 2: Identify and inspect the target exchange

The selected foreground-to-background boundary exchange is:

```text
Foreground process: Mock plastic broom assembly
process_index: 0
input_index: 1
Amount: 0.1055 ton kilometer

Current provider database: mock_background
Current provider code: mock-small-truck
Current provider activity: Mock freight transport, small truck
```

The current provider supplies `freight transport` in `ton kilometer` at
location `MOCK`.

Its recipe per ton-kilometer is:

| Type | Input or flow | Amount |
| --- | --- | ---: |
| Technosphere | Mock grid electricity, medium voltage | 0.08 kWh |
| Biosphere | Carbon dioxide, fossil | 0.09 kg |
| Biosphere | Sulfur dioxide | 0.0001 kg |

## Completed stage 3: Search for candidates

Candidate discovery used the read-only `search.sqlite3` projection. Both broad
text search and an exact structured query returned the same two activities for:

```text
Reference product: freight transport
Unit: ton kilometer
Location: MOCK
```

The results were:

| Role | Code | Activity |
| --- | --- | --- |
| Current provider | `mock-small-truck` | Mock freight transport, small truck |
| Candidate | `mock-small-truck-direct` | Mock freight transport, small truck, direct emissions only |

The projection reported itself as fresh. No LCA impact categories were scored
during candidate discovery.

## Completed stage 4: Inspect and validate the candidate

The candidate recipe contains:

| Type | Input or flow | Amount |
| --- | --- | ---: |
| Biosphere | Carbon dioxide, fossil | 0.09 kg |
| Biosphere | Sulfur dioxide | 0.0001 kg |

The candidate has no technosphere electricity input. The exact recipe
difference is therefore:

```text
Baseline truck:  0.08 kWh grid electricity per ton-kilometer
Candidate truck: 0 kWh grid electricity per ton-kilometer
```

For the broom's `0.1055 ton kilometer` requirement, the candidate removes
`0.00844 kWh` from the modeled supply chain. From the mock recipe, the predicted
inventory reduction is approximately:

```text
0.003376 kg fossil CO2
0.000002532 kg sulfur dioxide
```

These are recipe-based predictions, not results from a scenario calculation.

The candidate was verified in both the fresh search projection and the
authoritative installed Brightway `mock_background` database.

Validation decision:

```text
Compatibility: review_required
Experiment decision: accepted for controlled workflow testing
Scientific approval: not established
```

Hard checks passed for exact identity, activity type, reference product, unit,
location, and use of the same exchange amount in this controlled test.

The retained warning is:

> The candidate may represent an incomplete system boundary rather than a
> genuinely more efficient freight technology. It supplies the same product,
> but omits the baseline provider's upstream electricity input.

The expected lower score is useful for testing the workflow, but must not be
presented as proof that the candidate is environmentally superior.

## No scenario mutation has happened yet

At this pause point:

- the baseline product graph is unchanged;
- no candidate scenario has been calculated;
- no DoltLite scenario database exists;
- no scenario branch has been created; and
- `search.sqlite3` and the Brightway background databases remain unchanged.

## Dolt and DoltLite tooling status

This machine currently has the standalone Dolt CLI:

```text
dolt version 1.78.3
```

It does not currently have the separate `doltlite` CLI. Dolt and DoltLite are
different products:

- Dolt is a standalone MySQL-compatible version-controlled database.
- DoltLite is an embedded SQLite-compatible engine with version-control SQL
  functions such as `dolt_commit()`, `dolt_branch()`, and `dolt_merge()`.

For the scenario architecture in the plan, install and test the DoltLite CLI.
Application integration will probably also require the Python `doltlite`
package.

The Python binding has an important runtime constraint: according to its
official documentation, it works with dynamically linked SQLite builds such as
Homebrew Python on macOS, but not with the standalone Python builds commonly
installed by `uv`. This repository runs through `uv`, so the active Python and
SQLite linkage must be checked before adding the dependency.

Official references:

- [DoltLite repository and CLI installation](https://github.com/dolthub/doltlite)
- [DoltLite Python binding](https://github.com/dolthub/doltlite-python)

## Resume here

The next stage is an installation compatibility check:

1. identify the Python executable used by this project's virtual environment;
2. determine whether its `_sqlite3` module is dynamically or statically linked;
3. select and pin a DoltLite release;
4. install and verify the `doltlite` CLI; and
5. verify a supported Python integration path.

After that check, create the minimal scenario repository, save the unchanged
baseline on `main`, and create a branch for the accepted experimental freight
candidate. Do not change the product graph before the baseline commit exists.
