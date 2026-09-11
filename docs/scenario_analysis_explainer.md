# Explainer: Exploring Product-Graph Alternatives with SQLite and DoltLite

This document explains the early steps of the proposed scenario-analysis
workflow in [Plan: Searchable, Branchable LCA Scenario Analysis](../plans/PLAN_searchable_scenario_analysis.md).
It focuses on where alternatives are found, what is changed, and what DoltLite
branches preserve while scenarios are explored.

The short version is:

> Search in SQLite, preserve scenario choices in DoltLite, and calculate with
> Brightway.

## The systems have different responsibilities

| System | Responsibility |
| --- | --- |
| Product-graph YAML | Canonical description of the foreground model and its links to background providers |
| `search/search.sqlite3` | Read-only, disposable search projection used to discover background activities |
| DoltLite | Durable, version-controlled repository for baseline and scenario product graphs |
| Brightway background databases | Authoritative installed activities used in calculations |
| Temporary Brightway foreground database | Per-request realization of the product graph; deleted after the calculation |

Neither `search.sqlite3` nor the shared Brightway background databases are
modified when a scenario selects a different provider.

## Step 1: Establish the baseline

Begin with an existing product graph, such as the plastic broom. Validate and
normalize its YAML, record its functional unit and LCIA configuration, and run
an exact baseline calculation.

For an interactive REST client, the plan uses:

```http
POST /api/lca/base
```

This is the REST equivalent of `run_lca_base`. It accepts the same product-graph
YAML as `POST /api/lca/run`, but does not generate contribution graphs during
the initial request. Specific contribution graphs can be requested later with
`POST /api/lca/contribution` when hotspot analysis needs them.

The saved baseline identity includes the canonical product-graph hash,
functional unit, LCIA method and categories, background fingerprints, exact
scores and units, and the DoltLite commit hash when the baseline has already
been committed.

## Step 2: Select a foreground-to-background exchange

Choose one input at the boundary between the foreground model and a background
provider:

```text
Background provider
        | supplies material, energy, transport, etc.
        v
Foreground process
```

For example:

```text
Background: polypropylene production, global
        | 1.2 kg polypropylene
        v
Foreground: broom production
```

In valid product-graph YAML, this is an input on a foreground process with a
`database` and `code` identifying the background activity. The target record
keeps the exact `process_index` and `input_index`, so a scenario changes exactly
one exchange rather than every input with a similar name.

The target can be selected directly by the user, identified as an impact
hotspot, or derived from a stated goal such as reducing climate impact while
limiting any increase in water use.

## Step 3: Search for background alternatives

Search the read-only projection:

```text
search/search.sqlite3
```

It contains searchable records projected from shared background inventories
such as `bafu` and `mock_background`. It supports searches across activity
names, reference products, units, locations, classifications, synonyms, and
direct exchanges.

The process is:

1. Read the current provider's exact `(database, code)` identity.
2. Inspect its reference product, unit, location, classification, and direct
   recipe.
3. Search the SQLite projection for potentially compatible providers.
4. Validate and rank the candidates.
5. Retain the exact `(database, code)` identity of each plausible candidate.

SQLite is not authoritative and does not perform the LCA. Before applying a
candidate, confirm that its identity still exists in the current projection
and the corresponding installed Brightway background database.

## Step 4: Change the product graph, not the background database

Selecting an alternative changes the foreground input's provider reference.
For example:

```yaml
# Baseline
- product: polypropylene
  amount: 1.2
  unit: kg
  database: bafu
  code: original-provider-code
```

becomes:

```yaml
# Scenario
- product: polypropylene
  amount: 1.2
  unit: kg
  database: bafu
  code: alternative-provider-code
```

This does not edit the selected BAFU activity. It changes which existing
background activity the foreground points to.

The amount can remain `1.2 kg` only after validating that the products and
units are functionally compatible. Incompatible products or units require an
approved conversion, an explicit engineering rule, or manual review. Amounts
must not be copied silently between incompatible exchanges.

During calculation, Brightway creates a temporary foreground database from the
scenario product graph, connects it to the referenced installed background
activities, calculates the result, and deletes the temporary foreground
database.

## Step 5: Preserve plausible scenarios as DoltLite branches

DoltLite branches begin after search results have been validated and a
candidate is plausible enough to explore. Do not create a complete branch for
every raw search result.

For example:

```text
main
|-- scenario/recycled-polypropylene
|-- scenario/polypropylene-ch
`-- scenario/bio-based-polypropylene
```

Each branch preserves a different foreground choice:

```text
main
`-- polypropylene input -> original provider

scenario/recycled-polypropylene
`-- polypropylene input -> recycled provider

scenario/polypropylene-ch
`-- polypropylene input -> Swiss provider
```

A scenario revision should retain:

- the complete canonical product graph;
- the precise before-and-after exchange;
- the candidate's `(database, code)` identity;
- the rationale and compatibility findings;
- the search evidence and source fingerprint;
- its review status; and
- calculation records and provenance.

The DoltLite commit, normalized model revision, and canonical product-graph
hash must be linked. A branch name by itself is not a unique calculation
identity.

## The exploration loop

The working loop is:

```text
Calculate the baseline
        |
        v
Select one foreground-to-background exchange
        |
        v
Search many candidates in search.sqlite3
        |
        v
Validate and rank candidates
        |
        v
Create DoltLite branches for plausible alternatives
        |
        v
Run an exact Brightway calculation for each retained scenario
        |
        v
Reject, revise, retain as experimental, or approve
```

Rejected candidates can remain in the evidence record without becoming full
scenario branches. Plausible alternatives can remain as durable branches while
their environmental results, technical equivalence, and feasibility are
reviewed.
