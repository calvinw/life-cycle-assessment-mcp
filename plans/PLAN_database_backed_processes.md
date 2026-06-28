# Plan: Database-Backed Process Inputs in Recipe Cards

## Decision: Replace gdt-server with Brightway 2.5

The openLCA gdt-server Docker setup is replaced entirely with
**Brightway 2.5** (`pip install brightway25`). This eliminates Java, Docker,
and REST overhead from the calculation stack. The entire LCA engine runs
in-process as pure Python using numpy/scipy for matrix operations.

### Why Brightway 2.5

- Mature Python LCA framework (~12 years, standard in academic research)
- Activity Browser and many production LCA tools are built on it
- The recursive product system building we need is native behaviour
- `bw2io 0.9.x` imports USLCI, Ecoinvent, and openLCA JSON-LD natively
- No Docker, no Java, no REST serialization overhead
- Direct numpy/scipy matrix access — the A and B matrices are Python objects
- Core calculation engine (`bw2calc`) is very stable

### Version

Install via: `pip install brightway25`

This installs Brightway **2.5** (bw2data 4.x, bw2calc 2.x, bw2io 0.9.x,
bw_processing, matrix_utils). Do not confuse with the experimental
"Brightway25 next-generation rewrite" which is a separate, unfinished project.

### What is Removed

- `docker-compose.yml` gdt-server service (and any database service overlays)
- Java / openLCA gdt-server
- `olca_ipc` Python dependency
- All `RestClient` usage in `lca_engine.py`
- `~/olca-data` volume mounts
- The `lca_methods` openLCA database (LCIA methods are loaded via `bw2io`)

---

## Problem Statement

Currently, every number in a recipe card — all flows, emissions, and resource
extractions — is hand-authored directly in the YAML. For a production LCA
server we want process inputs to optionally link to real background inventory
databases (USLCI and others) so that upstream supply chains are resolved
accurately by the solver.

The system supports a **hybrid model**: if an input has explicit amounts in the
recipe card, use them; if an input has no amounts, look it up in the database
and resolve its upstream supply chain recursively. This matches how openLCA
desktop works when mixing foreground unit processes with background database
processes.

---

## Current Architecture (How Numbers Flow Today)

```
Recipe Card (YAML)
  └─ processes[i]
       ├─ reference_output: { flow, amount }
       ├─ inputs: [{ flow, amount }]         ← foreground links only (A-matrix)
       ├─ emissions: [{ flow, amount }]      ← hand-authored (B-matrix)
       └─ resources: [{ flow, amount }]      ← hand-authored (B-matrix)

lca_engine.py
  └─ RestClient → HTTP → gdt-server (Java) → A⁻¹f → HTTP → Python
```

---

## Target Architecture

```
Recipe Card (YAML)
  └─ processes[i]
       ├─ reference_output: { flow, amount }
       ├─ inputs: [{ flow, amount }]              ← foreground (hand-authored)
       │          [{ flow, amount, db_ref }]      ← pinned database lookup
       │          [{ flow, amount }]              ← implicit database search
       ├─ emissions: [{ flow, amount }]           ← hand-authored direct emissions
       └─ resources: [{ flow, amount }]           ← hand-authored direct resources

lca_engine.py (rewritten)
  └─ Brightway 2.5 in-process
       ├─ bw2data  — activity/database storage (SQLite)
       ├─ bw2io    — database import (USLCI, openLCA JSON-LD, etc.)
       ├─ bw2calc  — LCA calculation (sparse LU, numpy/scipy)
       └─ matrix_utils — A and B matrix construction
```

No network calls during calculation. Everything is in-process Python.

---

## Background Databases

The following free/open databases are imported once into Brightway projects on
first run and reused across calculations.

| Short name | Source | Import method |
|------------|--------|---------------|
| `uslci` | US Life Cycle Inventory | `bw2io` + UBW pipeline or direct ecospold/JSON-LD import |
| `biosphere` | FEDEFL / ecoinvent biosphere | `bw2io.create_default_biosphere3()` |
| `lcia_methods` | TRACI 2.2, ReCiPe, etc. | `bw2io.import_ecoinvent_lcia_methods()` |

A `scripts/setup_databases.py` script handles first-run import. Subsequent
runs reuse the Brightway project from disk (SQLite, stored in
`~/.local/share/Brightway3/` by default).

---

## Hybrid Resolution Logic

### Decision Tree for Each Input

For every input entry in a recipe card process:

```
Does the input have explicit emission/resource amounts in the recipe card?
  YES → use those amounts directly (foreground, unchanged behaviour)
  NO  → does the input have a db_ref?
          YES → fetch the pinned process from the named database
          NO  → search loaded databases for a provider of this flow
                  FOUND → link as background process, recurse into its inputs
                  NOT FOUND → cut-off with warning in unlinked_flows
```

### Recipe Card Syntax

```yaml
inputs:
  # 1. Fully hand-authored — no database lookup
  - flow: N-fertilizer
    amount: 0.2
    unit: kg

  # 2. Implicit database search — amount is quantity consumed,
  #    emissions come entirely from the database process
  - flow: Electricity
    amount: 0.45
    unit: kWh

  # 3. Pinned to a specific database and process
  - flow: Electricity
    amount: 0.45
    unit: kWh
    db_ref:
      source: uslci
      process: "Electricity, at grid/US"
```

---

## Schema Changes to Recipe Cards

### Modified `inputs` entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `flow` | string | yes | Flow name |
| `amount` | number | yes | Quantity consumed per reference output unit |
| `unit` | string | yes | Unit of measure |
| `db_ref` | object | no | Pin to a specific database process |
| `db_ref.source` | string | yes if db_ref | Named database (`uslci`, etc.) |
| `db_ref.process` | string | yes if db_ref | Activity name or UUID in that database |
| `db_ref.allocation` | string | no | `mass`, `economic`, `physical`, `none` (default) |

An input with no hand-authored emission amounts and no `db_ref` triggers
implicit database search. An input with hand-authored amounts is always
used as-is and never touches the database.

### New optional top-level section: `databases`

```yaml
databases:
  uslci:
    brightway_project: lca_server   # Brightway project name
    brightway_database: uslci       # database name within that project
```

If omitted, the server's default Brightway project and database priority list
from `config.yml` are used.

---

## Recursive Resolution

### How It Works in Brightway 2.5

In Brightway, every Activity (process) has Exchanges (inputs/outputs). The
`ProductSystemBuilder` traverses these recursively, mirroring openLCA desktop's
"auto-complete product system":

```python
def resolve(activity, visited=None):
    if visited is None:
        visited = set()
    if activity.key in visited:
        return          # cycle detected — A-matrix diagonal handles this
    visited.add(activity.key)

    for exc in activity.technosphere():
        provider = find_provider(exc.input)
        if provider:
            link(provider, activity, exc)
            resolve(provider, visited)   # recurse
        else:
            record_gap(exc, activity)    # cut-off
```

Brightway's `bw2calc.LCA` receives the complete activity graph and builds the
full sparse A and B matrices internally. The solve is `s = A⁻¹ f` using
scipy sparse LU decomposition (UMFPACK).

### Termination Conditions

- Activity has no further technosphere inputs (elementary process)
- Activity UUID already in `visited` (cycle)
- No provider found in any loaded database (cut-off)

---

## Handling Missing Upstream Processes (Gaps)

When a database activity has an input that cannot be found in any loaded
database, the engine applies **cut-off** (the industry default for attributional
LCA). The unlinked demand is excluded from the calculation.

### Reporting

Every result includes `unlinked_flows`:

```json
"unlinked_flows": [
  {
    "flow": "Sulfuric acid",
    "unit": "kg",
    "amount": 0.003,
    "consuming_process": "Electricity, at grid/US [uslci]",
    "reason": "no provider found in loaded databases"
  }
]
```

### Gap Filling Options (explicit, never automatic)

1. Add a foreground process to the recipe card modelling the missing upstream
2. Load an additional database that contains the missing process
3. Add a `db_ref` override on the specific input pointing to a proxy process

---

## Implementation Plan

### Phase 0 — Remove gdt-server, Add Brightway

1. Remove gdt-server from `docker-compose.yml` (or remove the file entirely
   if it only served gdt-server)
2. Remove `olca_ipc` from dependencies
3. Add to `requirements.txt` (or `pyproject.toml`):
   ```
   brightway25>=1.0
   bw2io>=0.9
   ```
4. Write `scripts/setup_databases.py`:
   - Creates/opens a Brightway project (`bw2data.projects.set_current(...)`)
   - Imports biosphere flows (`bw2io.create_default_biosphere3()`)
   - Imports LCIA methods (`bw2io.import_ecoinvent_lcia_methods()`)
   - Imports USLCI (via `bw2io` USLCI importer or UBW pipeline)
   - Idempotent — skips steps already completed

---

### Phase 1 — Rewrite lca_engine.py for Brightway

Replace all `RestClient` / openLCA object construction with Brightway
equivalents.

**Foreground process construction (from recipe card):**
```python
import bw2data as bd

db = bd.Database("foreground")
activity = db.new_activity(
    name=proc["name"],
    unit=proc["reference_output"]["unit"],
    location="GLO",
)
activity.save()

# Reference output
activity.new_exchange(
    input=activity,
    amount=proc["reference_output"]["amount"],
    type="production",
).save()

# Hand-authored emissions
for em in proc.get("emissions", []):
    flow = bd.get_activity(name=em["flow"], database="biosphere")
    activity.new_exchange(
        input=flow,
        amount=em["amount"],
        type="biosphere",
    ).save()
```

**Database-backed input (implicit or db_ref):**
```python
provider = provider_search.find(inp["flow"], inp["unit"])
if provider:
    activity.new_exchange(
        input=provider,
        amount=inp["amount"],
        type="technosphere",
    ).save()
    # Brightway/bw2calc resolves provider's upstream automatically
```

---

### Phase 2 — Provider Search

**File:** `lca_engine.py` (`ProviderSearch` class)

```python
def find(flow_name, unit, db_ref=None):
    if db_ref:
        db = bd.Database(db_ref["source"])
        return db.get(name=db_ref["process"])  # or by UUID

    # Implicit search: check databases in priority order
    for db_name in config.database_priority:
        db = bd.Database(db_name)
        matches = [a for a in db if a["name"] == flow_name
                   and a["unit"] == unit
                   and a["type"] == "process"]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            warn(f"Ambiguous provider for {flow_name} in {db_name}")
            return matches[0]
    return None
```

Cache results keyed on `(flow_name, unit)`.

---

### Phase 3 — LCA Calculation

```python
import bw2calc as bc

lca = bc.LCA(
    demand={reference_activity: functional_unit_amount},
    method=("TRACI 2.2", "human health", "..."),
)
lca.lci()    # builds and solves A⁻¹f, produces inventory
lca.lcia()   # applies characterization factors → impact scores
```

Results map directly to the existing output format:
- `lca.inventory` → `lci` dict
- `lca.score` / `lca.characterized_inventory` → `lcia` dict
- `lca.supply_array` → `scaling_vector` (one entry per activity in graph)

---

### Phase 4 — Results and Gap Reporting

Collect `unlinked_flows` during Phase 1 traversal (any `find()` call that
returns `None`). Include in the result dict alongside existing keys.

Background process entries in `scaling_vector` are labelled with their source
database: `"Electricity, at grid/US [uslci]": 0.45`.

---

### Phase 5 — Validation

**File:** new `lca_validator.py`

- Validate `db_ref` fields at parse time
- After provider search, warn on ambiguous matches
- Report unlinked flow count in validation summary

---

### Phase 6 — SVG Visualization

**File:** `lca_svg.py` — minimal changes needed

- Background activities render as real nodes (they already appear in the
  activity graph from Brightway traversal)
- Distinct fill color for database-sourced vs. foreground processes
- Label includes source database name
- Unlinked flows shown as dashed arrows with `⚠ cut-off` label
- Configurable upstream depth cutoff before collapsing to summary node

---

### Phase 7 — Bundle Generation

**File:** `generate_bundles.py`

- Record Brightway project name and database versions in `bundle_metadata`
- Serialize the resolved activity graph (all keys + exchange amounts) into the
  bundle so bundles can be inspected offline
- Include `unlinked_flows` in bundle for transparency

---

## Recipe Card Example (Hybrid Mode)

```yaml
name: "Cotton Fiber — 1 kg"
goal: "Hybrid LCA: foreground processes with USLCI background inputs"

lcia:
  method_name: TRACI 2.2

functional_unit:
  description: 1 kg of cotton fiber
  amount: 1.0
  unit: kg

units:
  kg: Mass
  kWh: Energy
  L:   Volume
  MJ:  Energy

products:
  - { name: N-fertilizer, unit: kg }
  - { name: Cotton fiber, unit: kg }

elementary_flows:
  emissions:
    - { name: Carbon dioxide, compartment: air, unit: kg }
    - { name: Nitrous oxide,  compartment: air, unit: kg }
  resources:
    - { name: Water, compartment: water, unit: L }

processes:
  - name: P1 — Fertilizer production
    reference_output: { flow: N-fertilizer, amount: 1.0, unit: kg }
    inputs:
      # Implicit database search — engine finds natural gas in USLCI
      - { flow: Natural gas, amount: 12.5, unit: MJ }
    emissions:
      - { flow: Carbon dioxide, amount: 3.5, unit: kg }

  - name: P2 — Cotton farming
    reference_output: { flow: Cotton fiber, amount: 1.0, unit: kg }
    inputs:
      # Foreground link to our own P1 (unchanged)
      - { flow: N-fertilizer, amount: 0.2, unit: kg }
      # Pinned to specific USLCI process
      - flow: Electricity
        amount: 0.45
        unit: kWh
        db_ref:
          source: uslci
          process: "Electricity, at grid/US"
    emissions:
      - { flow: Nitrous oxide, amount: 0.015, unit: kg }
    resources:
      - { flow: Water, amount: 850.0, unit: L }

reference_process: P2 — Cotton farming
```

---

## What Does NOT Change

- Recipe card YAML format is backward compatible — existing cards with all
  amounts hand-authored work without modification
- LCIA method names in recipe cards (`TRACI 2.2`, etc.) are unchanged
- Output keys (`lci`, `lcia`, `scaling_vector`) are unchanged in structure
- `lca_svg.py` SVG generation is largely unchanged

---

## Open Questions / Decisions Needed

1. **Brightway project name**: single project for all databases (`lca_server`)
   or one project per database? Recommendation: **single project**, multiple
   named databases within it (`uslci`, `biosphere`, `foreground`).

2. **Provider search priority**: when multiple databases have a provider,
   which wins? Recommendation: configurable list in `config.yml`, defaulting
   to `uslci → biosphere`.

3. **SVG upstream depth cutoff**: how many levels to render before collapsing.
   Recommendation: default 2, configurable per recipe card.

4. **UUID vs. name in `db_ref.process`**: Recommendation: if value parses as
   UUID use direct lookup; otherwise search by name, error if ambiguous.

---

## File Change Summary

| File | Change |
|------|--------|
| `docker-compose.yml` | Remove gdt-server service entirely |
| `requirements.txt` | Replace `olca_ipc` with `brightway25`, `bw2io` |
| `lca_engine.py` | Full rewrite: Brightway 2.5 replaces all RestClient/openLCA object code |
| `lca_svg.py` | Minor updates: background node styling, cut-off labels |
| `generate_bundles.py` | Record Brightway database versions; embed activity graph |
| `config.yml` | New: Brightway project name, database priority list |
| `scripts/setup_databases.py` | New: first-run database import (biosphere, LCIA, USLCI) |
| New: `lca_validator.py` | Parse-time and post-search validation |
| `case_studies/*.md` | Add `db_ref` or implicit inputs as needed per case study |
