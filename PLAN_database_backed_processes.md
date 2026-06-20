# Plan: Database-Backed Process Inputs in Recipe Cards

## Problem Statement

Currently, every number in a recipe card — all flows, emissions, and resource
extractions — is hand-authored directly in the YAML. For a production LCA
server we want process inputs to optionally link to real background inventory
databases (USLCI, openLCA reference data, and other free databases) so that
upstream supply chains are resolved accurately by the solver.

The system should support a **hybrid model**: if an input has explicit amounts
in the recipe card, use them; if an input has no amounts, look it up in the
database and resolve its upstream supply chain recursively. This is how openLCA
desktop works when you mix foreground unit processes with background database
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
```

The gdt-server performs `s = A⁻¹ f` at calculation time.

The database (`lca_methods`) currently holds **only** LCIA methods and FEDEFL
elementary flow definitions — no inventory processes.

---

## Background Databases to Load

The following free/open databases will be imported into the gdt-server as
openLCA JSON-LD archives. Each requires a separate gdt-server instance (or
database slot) since gdt-server opens one database at a time.

| Short name | Database | Notes |
|------------|----------|-------|
| `uslci` | US Life Cycle Inventory (USLCI) | Free, ~1000 processes, US focus |
| `glad` | Global LCA Data (GLAD) | Free aggregated datasets |
| `openlca_ref` | openLCA reference data | Unit groups, flow properties, FEDEFL flows |

Ecoinvent is excluded (requires license) but the architecture supports adding
it later.

**Loading mechanism:** A Docker Compose service per database, each running its
own gdt-server instance with the database volume pre-populated by an import
script (`scripts/import_database.py`) that fetches the JSON-LD zip and POSTs
it to the server's import endpoint on first run.

---

## Hybrid Resolution Logic

### Decision Tree for Each Input

For every input entry in a recipe card process, the engine applies this logic:

```
Does the input have explicit emission/resource amounts in the recipe card?
  YES → use those amounts directly (existing foreground behaviour, unchanged)
  NO  → does the input have a db_ref?
          YES → look up the named process in the specified database
                and link it as a real A-matrix node (see Phase 3)
          NO  → does a process in any loaded database produce this flow?
                  YES → auto-link it (implicit db_ref, see below)
                  NO  → leave as unlinked (cut-off, with warning)
```

### Simplified Recipe Card Syntax

Rather than always requiring an explicit `db_ref` block, inputs that have no
amounts are treated as implicit database lookups:

```yaml
inputs:
  # Explicit amounts → used as-is, no database lookup
  - { flow: N-fertilizer, amount: 0.2, unit: kg }

  # No amounts → engine searches loaded databases for a provider
  - { flow: Electricity, unit: kWh, amount: 0.45 }
    # amount here is the QUANTITY consumed, not the emissions per unit
    # emissions come entirely from the database process

  # Explicit db_ref → pin to a specific database and process name
  - flow: Electricity
    amount: 0.45
    unit: kWh
    db_ref:
      source: uslci
      process: "Electricity, at grid/US"
```

The `amount` field on a database-backed input is always the **quantity
consumed** (e.g., 0.45 kWh). The database process supplies the emissions and
upstream inputs per unit of that flow. The engine scales by `amount` when
building the technosphere link.

---

## Schema Changes to Recipe Cards

### Modified `inputs` entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `flow` | string | yes | Flow name |
| `amount` | number | yes | Quantity consumed per reference output |
| `unit` | string | yes | Unit of measure |
| `emissions` | list | no | If present, hand-authored amounts are used (foreground) |
| `db_ref` | object | no | Pin to a specific database process |
| `db_ref.source` | string | yes if db_ref | Named database from registry |
| `db_ref.process` | string | yes if db_ref | Process name or UUID in that database |
| `db_ref.allocation` | string | no | `mass`, `economic`, `physical`, `none` (default) |

If neither `emissions` nor `db_ref` is present and the flow has no hand-authored
amounts, the engine performs an implicit database search.

### New top-level section: `databases`

```yaml
databases:
  uslci:
    type: olca_gdt
    url: http://localhost:8081   # separate gdt-server instance per database
  glad:
    type: olca_gdt
    url: http://localhost:8082
```

If `databases` is omitted, only the default `lca_methods` instance is
available (existing behaviour).

---

## Recursive Resolution

### How it Works

When the engine links a background process to a foreground process, that
background process may itself have inputs that are also in the database. The
engine resolves these recursively:

```
resolve(process P):
  for each input I of P:
    if I has explicit amounts in the recipe card:
      add to A-matrix as foreground exchange
    else:
      provider = find_provider(I.flow, loaded_databases)
      if provider found:
        add provider to product system if not already present
        add technosphere link: provider → P
        resolve(provider)          # recurse
      else:
        mark I as unlinked (cut-off)
        emit warning
```

This matches the openLCA desktop "auto-complete product system" behaviour
exactly. The recursion terminates when:
- A process has no further inputs in any loaded database (all inputs are either
  hand-authored or unlinked), or
- A cycle is detected (the same process UUID appears twice in the current
  resolution path — openLCA handles this via the A-matrix diagonal)

The engine tracks visited process UUIDs to avoid infinite loops in circular
supply chains (e.g., process A uses output of process B, which uses output of
process A).

### Where the Recursion Lives

The gdt-server's `POST /calculate` endpoint does **not** auto-complete the
product system. The Python engine must build the complete `ProductSystem` object
(all process refs + all process links) before submitting the calculation. The
recursive resolver in Python produces this complete graph.

This is consistent with how the openLCA IPC Python library works when used
programmatically (as opposed to the desktop GUI's auto-complete button).

---

## Handling Missing Upstream Processes (Gaps)

When a database process has an input that cannot be found in any loaded
database, the engine must decide what to do. openLCA desktop calls these
"unlinked flows" and handles them via the **cut-off** approach by default.

### Cut-Off (Default)

The unlinked input is simply not connected to any upstream provider. Its demand
propagates to the technosphere but has no upstream to resolve — effectively it
disappears from the calculation. This is the industry-standard approach for
attributional LCA with system boundary cut-offs (e.g., Ecoinvent cutoff system
model).

The calculation still produces valid results; the unlinked flows represent
inputs whose upstream burden is intentionally excluded at the system boundary.

### How Gaps Are Reported

Every calculation result includes an `unlinked_flows` section listing all
flows that were cut off:

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

This gives the user visibility into what is and isn't accounted for, which is
standard practice in professional LCA reporting.

### Future: Gap-Filling

If a gap is significant, the recipe card author can fill it by:
1. Adding a foreground process to the recipe card that models the missing
   upstream (hand-authored amounts)
2. Loading an additional database that contains the missing process
3. Adding a `db_ref` override on the specific input pointing to a proxy process

No automatic gap-filling is implemented; all gap decisions are explicit.

---

## Implementation Plan

### Phase 0 — Database Loading Infrastructure

**New files:** `docker-compose.databases.yml`, `scripts/import_database.py`

1. Add a Docker Compose overlay with one gdt-server service per background
   database (USLCI, GLAD), each on its own port.
2. Write an import script that:
   - Downloads the openLCA JSON-LD zip for each database from the official
     source (openLCA Nexus or GitHub releases)
   - POSTs the zip to `PUT /data` on the respective gdt-server instance
   - Verifies import by checking process count
3. Add a `databases` registry to a server config file (not in recipe cards)
   so all recipe cards share it without repeating connection details.

---

### Phase 1 — Database Registry

**File:** `lca_engine.py` (new `DatabaseRegistry` class)

1. Load the server-level database registry from config.
2. Build `{source_name -> RestClient}`.
3. Expose `get_client(source_name)` and `all_clients()` (for implicit search).

---

### Phase 2 — Provider Search

**File:** `lca_engine.py` (new `ProviderSearch` class)

```
find_provider(flow_name, flow_unit) -> (RestClient, olca.Process) | None
```

1. Search all loaded databases in priority order (uslci → glad → ...) for a
   process whose reference output matches `flow_name` and `flow_unit`.
2. If multiple providers match, prefer the one whose reference output unit
   matches exactly; otherwise raise an ambiguity warning and use the first.
3. If `db_ref` is specified, skip the search and fetch directly from the named
   database.
4. Cache results keyed on `(flow_name, flow_unit)`.

---

### Phase 3 — Recursive Product System Builder

**File:** `lca_engine.py` (new `ProductSystemBuilder` class)

```python
class ProductSystemBuilder:
    def __init__(self, registry, provider_search):
        self.visited = set()        # process UUIDs already added
        self.process_links = []
        self.processes = []

    def add_process(self, process, client):
        if process.id in self.visited:
            return
        self.visited.add(process.id)
        self.processes.append(process.to_ref())

        for exchange in process.exchanges:
            if exchange.is_input and not exchange.is_avoided_product:
                provider, p_client = self.provider_search.find(exchange.flow)
                if provider:
                    self.process_links.append(
                        make_link(provider, process, exchange)
                    )
                    self.add_process(provider, p_client)  # recurse
                else:
                    self.unlinked.append(make_gap_record(exchange, process))
```

The final `ProductSystem` object passed to `POST /calculate` contains the
complete pre-built graph.

---

### Phase 4 — Calculation and Results

No changes to the `POST /calculate` call itself. The gdt-server receives a
fully-specified `ProductSystem` and returns LCI + LCIA results as today.

Output additions:
- `scaling_vector` gains entries for all background processes, labelled with
  their source database: `"Electricity, at grid/US [uslci]": 0.45`
- New `unlinked_flows` array (see Gap Handling above)
- New `background_process_count` integer for quick visibility into how many
  database processes were resolved

---

### Phase 5 — Validation

**File:** new `lca_validator.py`

- Validate `db_ref` fields at parse time before any network calls.
- After provider search, warn on ambiguous matches (multiple providers for same
  flow).
- After build, report total unlinked flow count in validation summary.

---

### Phase 6 — SVG Visualization

**File:** `lca_svg.py`

- Background processes render as real nodes with distinct fill color.
- Label includes source database: `"Electricity, at grid/US\n[uslci]"`.
- Upstream recursion depth is configurable; beyond the threshold, a collapsed
  `"... N upstream processes [uslci]"` summary node is shown.
- Unlinked flows shown as dashed outbound arrows with a `"⚠ cut-off"` label.

---

### Phase 7 — Bundle Generation

**File:** `generate_bundles.py`

- Record database versions in `bundle_metadata`.
- Serialize the complete resolved `ProductSystem` graph (all process refs and
  links) into the bundle JSON so bundles can be recalculated offline against a
  locally loaded database without re-running provider search.
- Include `unlinked_flows` in the bundle for transparency.

---

## Recipe Card Example (Hybrid Mode)

```yaml
name: "Cotton Fiber — 1 kg"
goal: "Hybrid LCA: some inputs hand-authored, some from USLCI"

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
      # Hand-authored: we know this number, don't need the database
      - flow: Water
        amount: 5.0
        unit: L
        resources:
          - { flow: Water, amount: 5.0, unit: L }

      # No amounts provided → engine searches USLCI for a natural gas process
      - flow: Natural gas
        amount: 12.5
        unit: MJ

    emissions:
      - { flow: Carbon dioxide, amount: 3.5, unit: kg }

  - name: P2 — Cotton farming
    reference_output: { flow: Cotton fiber, amount: 1.0, unit: kg }
    inputs:
      # Foreground link to our own P1 process (unchanged)
      - { flow: N-fertilizer, amount: 0.2, unit: kg }

      # Pinned to specific USLCI process by name
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

In this example:
- P1's water input is hand-authored (we have the number)
- P1's natural gas input triggers an implicit database search → USLCI returns
  a natural gas process → its upstream (extraction, transport) is resolved
  recursively
- P2's electricity input is pinned explicitly to a specific USLCI process
- Anything in the natural gas or electricity supply chains not found in USLCI
  is cut off and reported in `unlinked_flows`

---

## What Does NOT Change

- Recipe cards with all amounts hand-authored work exactly as before.
- LCIA characterization comes from `lca_methods` regardless of which inventory
  database supplies the emissions.
- The `POST /calculate` call to gdt-server is unchanged.
- Output keys (`lci`, `lcia`, `scaling_vector`) are unchanged in structure.

---

## Open Questions / Decisions Needed

1. **Server-level vs. recipe-level database registry**: Should the `databases`
   section live in a server config file (shared across all recipe cards) or
   per-recipe-card? Recommendation: **server config** (`config.yml`) with
   per-recipe optional overrides.

2. **Provider search priority order**: When multiple databases contain a
   provider for the same flow, which wins? Recommendation: explicit `db_ref`
   always wins; implicit search uses a configurable priority list in server
   config.

3. **Upstream SVG depth cutoff**: How many levels to render before collapsing.
   Recommendation: default 2 levels, configurable per recipe card.

4. **UUID vs. name in `db_ref.process`**: Recommendation: if the value parses
   as a UUID, use direct lookup; otherwise search by name and raise an error if
   ambiguous.

---

## File Change Summary

| File | Change |
|------|--------|
| `docker-compose.databases.yml` | New: one gdt-server service per background database |
| `scripts/import_database.py` | New: download and import JSON-LD database archives |
| `config.yml` | New: server-level database registry |
| `lca_engine.py` | Add `DatabaseRegistry`, `ProviderSearch`, `ProductSystemBuilder` with recursive resolution |
| `lca_svg.py` | Render background processes as real nodes; show cut-off warnings |
| `generate_bundles.py` | Record database versions; embed resolved product system graph |
| `case_studies/*.md` | Add `db_ref` fields or implicit database inputs as needed |
| New: `lca_validator.py` | Parse-time and post-search validation |
