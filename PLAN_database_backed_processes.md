# Plan: Database-Backed Process Inputs in Recipe Cards

## Problem Statement

Currently, every number in a recipe card — all flows, emissions, and resource
extractions — is hand-authored directly in the YAML. For a production LCA
server we want process inputs to link to real background inventory databases
(e.g., Ecoinvent, US LCI) so that upstream supply chains are resolved
accurately by the solver rather than approximated by hand.

The goal is to let a recipe card say "this process consumes 0.45 kWh of grid
electricity — link to the database process for that electricity and let openLCA
solve the full supply chain" rather than enumerating upstream emissions by hand.

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

Every amount ends up as an entry in the A-matrix (technosphere) or B-matrix
(biosphere). The gdt-server performs `s = A⁻¹ f` at calculation time.

The database (`lca_methods`) currently holds **only**:
- LCIA methods and characterization factors
- FEDEFL elementary flow definitions

It holds **no** background inventory processes (no electricity, no transport,
no fuels, etc.).

---

## How openLCA Desktop Works (Production Target)

In the openLCA desktop app, background processes are **real nodes** in the
product system connected via technosphere flows. They appear as columns in the
A-matrix alongside foreground processes, and the solver handles everything as
one unified matrix:

```
s = A⁻¹ f
```

Where A contains **all** processes — foreground and background — and f is the
demand vector. The solver scales every process simultaneously. Background
processes remain individually visible in the product system graph, with their
own scaling factors in the solution vector `s`.

This is what the gdt-server is designed to do. The production approach must
match it: background processes become real linked nodes, not pre-collapsed
emission grafts.

---

## Proposed Extension: `db_ref` Inputs

### Core Idea

Allow an input entry in a recipe card to declare itself as database-backed by
adding a `db_ref` field. The engine looks up that process in the background
database and creates a **real technosphere link** between the background process
and the foreground process — exactly as openLCA desktop would:

```yaml
processes:
  - name: P2 — Cotton farming
    reference_output: { flow: Cotton fiber, amount: 1.0, unit: kg }
    inputs:
      # Foreground input — unchanged, links to another recipe process
      - { flow: N-fertilizer, amount: 0.2, unit: kg }

      # Background input — links to a real database process
      - flow: Electricity, at grid, US
        amount: 0.45
        unit: kWh
        db_ref:
          source: uslci          # named database from the registry
          process: "Electricity, at grid/US"  # exact process name or UUID in DB
```

When `db_ref` is present, the engine:
1. Looks up the named process in the background database by name or UUID
2. Retrieves the Process object (including its own inputs, emissions, and
   resource flows)
3. Adds that Process as a column in the product system's A-matrix
4. Creates a technosphere link: background process reference output →
   foreground process input
5. Lets `A⁻¹ f` propagate the demand through the full supply chain recursively

The background process's entire upstream supply chain is resolved by the solver.
No manual scaling or emission grafting occurs.

---

## Schema Changes to Recipe Cards

### New optional field on any `inputs` entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `db_ref` | object | no | If present, this input links to a database process |
| `db_ref.source` | string | yes | Named database from the `databases` registry |
| `db_ref.process` | string | yes | Process name or UUID in that database |
| `db_ref.allocation` | string | no | Allocation method if multi-output: `mass`, `economic`, `physical`, `none` (default: `none`) |

### New top-level section: `databases`

```yaml
databases:
  uslci:
    type: olca_gdt
    url: http://localhost:8080
    database: uslci_corr
  ecoinvent:
    type: olca_gdt
    url: http://localhost:8080
    database: ecoinvent_391_cutoff
```

This registry decouples the `db_ref.source` short name from actual connection
details so recipe cards remain portable across deployments. If the `databases`
section is omitted, the default gdt-server instance is assumed.

---

## Implementation Plan

### Phase 1 — Background Database Registry

**File:** `lca_engine.py` (new `DatabaseRegistry` class)

1. Parse the `databases` section from the recipe YAML at startup.
2. Build a registry: `{source_name -> RestClient}`.
3. If no `databases` section, use the existing default `RestClient`.
4. Expose `get_client(source_name) -> RestClient` with clear error on missing
   source.

No recipe card format changes yet; pure infrastructure.

---

### Phase 2 — Background Process Resolver

**File:** `lca_engine.py` (new `BackgroundProcessResolver` class)

```
resolve(source, process_name_or_uuid) -> olca.Process
```

Steps:

1. Call `get_client(source)` to get the right database connection.
2. Search for the process by name (`GET /data/processes` filtered by name) or
   fetch directly by UUID.
3. Return the full `olca.Process` object as retrieved from the database —
   including all its exchanges (inputs, outputs, emissions, resources).
4. Cache results keyed on `(source, process_name_or_uuid)` to avoid repeated
   network calls within a single `run_analysis()` call.

The resolver does **not** pre-solve or collapse the process. It returns the raw
Process object so the engine can link it into the product system properly.

---

### Phase 3 — Product System Builder Update

**File:** `lca_engine.py` — process and product system construction

This is the core change. When iterating over `process.inputs`:

```python
for inp in process.get("inputs", []):
    if "db_ref" in inp:
        # Resolve the background process from the database
        bg_process = resolver.resolve(
            source=inp["db_ref"]["source"],
            process=inp["db_ref"]["process"],
        )
        # Add the background process to the product system as a real node
        product_system.processes.append(bg_process.to_ref())

        # Create a technosphere link: bg_process.ref_output → this process input
        link = olca.ProcessLink()
        link.provider = bg_process.to_ref()
        link.flow = bg_process.quantitative_reference.flow
        link.process = current_process.to_ref()
        link.exchange = find_input_exchange(current_process, inp["flow"])
        product_system.process_links.append(link)

        # The solver will traverse bg_process's own inputs recursively
    else:
        # Existing behaviour — foreground technosphere link (unchanged)
        add_foreground_link(inp)
```

The gdt-server's `POST /calculate` call already handles recursive supply chain
resolution when the product system graph is fully specified. No additional
recursion logic is needed in Python.

---

### Phase 4 — Handling Multi-Output Background Processes

**File:** `lca_engine.py`

When a background process has multiple outputs (e.g., a co-production process),
the engine must apply the allocation method specified in `db_ref.allocation`
before linking. openLCA supports this natively via the `AllocationMethod` field
in `CalculationSetup`:

```python
setup = olca.CalculationSetup()
setup.allocation_method = map_allocation(recipe.get("default_allocation", "none"))
```

Per-input overrides of allocation method are applied by creating a modified
copy of the background process with the specified allocation pre-applied, or by
using openLCA's process-level allocation factors if stored in the database.

Default: `none` (cut-off allocation), consistent with Ecoinvent cutoff system
model.

---

### Phase 5 — Scaling Vector and Results

The output `scaling_vector` already maps process name → scale factor. With
background processes included in the product system, the scaling vector will
now include entries for every background process the solver touched:

```json
"scaling_vector": {
  "P1 — Fertilizer production": 0.2,
  "P2 — Cotton farming": 1.0,
  "Electricity, at grid/US [uslci]": 0.45,
  "Steam, natural gas [uslci]": 0.031
}
```

Background process entries should be labelled with their source database in
brackets to distinguish them from foreground processes.

The existing `lci` and `lcia` output keys are unchanged — they already
represent the total system result after solver propagation.

---

### Phase 6 — Recipe Card Validation

**File:** new `lca_validator.py`

Validate before touching any database:

- If `db_ref` is present on an input, require both `db_ref.source` and
  `db_ref.process`.
- If `db_ref.source` names a database not in the `databases` registry, raise a
  clear error identifying the missing entry.
- Validate `db_ref.allocation` is one of the accepted values if provided.

At resolution time (Phase 2), raise a clear error if the named process cannot
be found in the specified database, including the source and process name in
the message.

---

### Phase 7 — SVG Visualization Update

**File:** `lca_svg.py`

Background processes are real nodes in the product system and should render as
real nodes in the SVG, visually distinct from foreground processes:

- Different fill color (e.g., light blue for foreground, light grey for
  background database processes).
- Label includes the source database name: `"Electricity, at grid/US\n[uslci]"`.
- Arrow from background node into foreground process, labelled with amount and
  unit, same as any other technosphere link.
- Background processes connected to other background processes (upstream supply
  chain) are rendered if their scaling factor is above a configurable threshold,
  collapsed to a single "upstream" node if the chain is too deep.

---

### Phase 8 — Bundle Generation Update

**File:** `generate_bundles.py`

Bundles containing `db_ref` inputs are database-dependent. The bundler should:

1. Record which background databases were queried and their version metadata:

```json
"bundle_metadata": {
  "generated_at": "2026-06-20T...",
  "database_versions": {
    "uslci": { "name": "uslci_corr", "version": "2023-07-01" }
  }
}
```

2. Optionally cache the resolved background `Process` objects as JSON in the
   bundle so that the recipe can be re-run offline without a live database
   connection. The engine checks for a `resolved_processes` section in the
   bundle and uses it instead of live lookups when present.

---

## Recipe Card Example (After Extension)

```yaml
name: "Cotton Fiber — 1 kg"
goal: "Full supply chain LCA linking electricity to USLCI"

databases:
  uslci:
    type: olca_gdt
    url: http://localhost:8080
    database: uslci_corr

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

products:
  - { name: N-fertilizer,   unit: kg }
  - { name: Cotton fiber,   unit: kg }

elementary_flows:
  emissions:
    - { name: Carbon dioxide, compartment: air, unit: kg }
    - { name: Nitrous oxide,  compartment: air, unit: kg }
  resources:
    - { name: Water,          compartment: water, unit: L }

processes:
  - name: P1 — Fertilizer production
    reference_output: { flow: N-fertilizer, amount: 1.0, unit: kg }
    inputs:
      # Background: natural gas from USLCI, full upstream resolved by solver
      - flow: Natural gas, at production
        amount: 12.5
        unit: MJ
        db_ref:
          source: uslci
          process: "Natural gas, combusted in industrial boiler"
    emissions:
      - { flow: Carbon dioxide, amount: 3.5, unit: kg }

  - name: P2 — Cotton farming
    reference_output: { flow: Cotton fiber, amount: 1.0, unit: kg }
    inputs:
      # Foreground link — stays in recipe card
      - { flow: N-fertilizer, amount: 0.2, unit: kg }
      # Background link — solver resolves full electricity supply chain
      - flow: Electricity, at grid, US
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

- Existing foreground-only recipe cards are **fully backward compatible**.
  `db_ref` is opt-in per input entry.
- The `lca_methods` database and LCIA characterization logic are unchanged.
- The `POST /calculate` call to gdt-server is unchanged; it already supports
  full product system graphs with arbitrary depth.
- Output keys (`lci`, `lcia`, `scaling_vector`) are unchanged in structure;
  `scaling_vector` gains additional entries for background processes.
- The matrix algebra (`A⁻¹ f`) is handled entirely by the gdt-server — no
  changes to solver logic.

---

## What This Replaces (vs. Previous Teaching Approximation)

The previous draft proposed "grafting" background emissions directly into the
foreground B-matrix (pre-solving and collapsing upstream flows by hand). That
approach was rejected because:

- It does not match how openLCA desktop works
- It loses the background process as a visible, individually-scalable node
- It requires manual maintenance if the background process changes in the DB
- It cannot represent multi-level upstream supply chains correctly
- It is not appropriate for a production LCA server

The correct approach — and what this plan implements — is to add background
processes as real A-matrix nodes linked via technosphere flows, and let the
gdt-server solver (`A⁻¹ f`) resolve the full supply chain as designed.

---

## Open Questions / Decisions Needed

1. **Which background databases to support initially?** USLCI is free and
   directly supported by openLCA. Ecoinvent requires a license. Recommendation:
   **USLCI first**, with the registry design making Ecoinvent straightforward
   to add.

2. **Upstream graph depth in SVG**: How many levels of background supply chain
   to render before collapsing to a summary node? Suggestion: configurable,
   defaulting to 2 levels.

3. **Process name vs. UUID in `db_ref.process`**: Name lookup is human-readable
   but fragile if the database has duplicate names. UUID lookup is robust but
   opaque. Recommendation: **support both** — if the value is a valid UUID,
   use direct lookup; otherwise search by name and raise an error if ambiguous.

4. **Offline bundle fallback**: Should pre-resolved Process objects be embedded
   in bundles for offline use? Recommendation: **yes**, as a serialized openLCA
   JSON archive alongside the bundle, loaded by the engine when no live
   database is available.

---

## File Change Summary

| File | Change |
|------|--------|
| `lca_engine.py` | Add `DatabaseRegistry`, `BackgroundProcessResolver`; update product system builder to create real A-matrix links for `db_ref` inputs |
| `lca_svg.py` | Render background processes as real nodes with distinct styling and configurable depth cutoff |
| `generate_bundles.py` | Record `database_versions`; optionally embed resolved Process objects for offline use |
| `case_studies/*.md` | Add `databases:` section and `db_ref` fields to inputs as needed |
| New: `lca_validator.py` | Schema and reference validation for `db_ref` fields before computation |
