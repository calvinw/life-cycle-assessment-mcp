# Plan: Database-Backed Process Inputs in Recipe Cards

## Problem Statement

Currently, every number in a recipe card — all flows, emissions, and resource
extractions — is hand-authored directly in the YAML. For teaching purposes
this is fine, but for more realistic case studies we want process inputs to be
pulled automatically from a background database (e.g., Ecoinvent, US LCI, or a
custom inventory) instead of typed by hand.

The goal is to let a recipe card say "this process consumes 0.3 kWh of grid
electricity — get the emissions profile of that electricity from the database"
rather than enumerating all the upstream emissions by hand.

---

## Current Architecture (How Numbers Flow Today)

```
Recipe Card (YAML)
  └─ processes[i]
       ├─ reference_output: { flow, amount }
       ├─ inputs: [{ flow, amount }]         ← all amounts are hand-authored
       ├─ emissions: [{ flow, amount }]      ← all amounts are hand-authored
       └─ resources: [{ flow, amount }]      ← all amounts are hand-authored
```

Every amount ends up as an entry in the A-matrix (technosphere) or B-matrix
(biosphere). The gdt-server performs `s = A⁻¹ f` at calculation time.

The database (`lca_methods`) currently holds **only**:
- LCIA methods and characterization factors
- FEDEFL elementary flow definitions

It holds **no** background inventory processes (no electricity, no transport,
no fuels, etc.).

---

## Proposed Extension: `db_ref` Inputs

### Core Idea

Allow an input entry in a recipe card to declare itself as database-backed by
adding a `db_ref` field instead of (or alongside) explicit emission/resource
amounts:

```yaml
processes:
  - name: P2 — Cotton farming
    reference_output: { flow: Cotton fiber, amount: 1.0, unit: kg }
    inputs:
      # Foreground input — amounts stay in the recipe card (unchanged)
      - { flow: N-fertilizer, amount: 0.2, unit: kg }

      # Background input — emissions pulled from database
      - flow: Electricity, US grid
        amount: 0.45
        unit: kWh
        db_ref:
          source: uslci          # which database/library to query
          process: "Electricity, at grid, US"   # exact process name in that DB
          # Optional overrides:
          allocation: mass       # allocation method if the DB process is multi-output
```

When `db_ref` is present, the engine looks up that process in the specified
background database, scales its elementary flows by `amount`, and folds them
into the current process's B-matrix column. The technosphere connection is
**not** added to the A-matrix (i.e., it stays a "cut-off" for the foreground
system; the background emissions are grafted in directly).

---

## Schema Changes to Recipe Cards

### New optional field on any `inputs` entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `db_ref` | object | no | If present, emissions for this input come from DB |
| `db_ref.source` | string | yes | Named database to query (see registry below) |
| `db_ref.process` | string | yes | Exact name (or UUID) of the background process |
| `db_ref.allocation` | string | no | Allocation method: `mass`, `economic`, `physical`, `none` |
| `db_ref.system_boundary` | string | no | `cradle_to_gate` (default) or `gate_to_gate` |

### New top-level section: `databases`

```yaml
databases:
  uslci:
    type: olca_gdt          # gdt-server REST endpoint
    url: http://localhost:8080
    database: uslci_corr    # database name within the server
  custom_ecoinvent:
    type: olca_gdt
    url: http://localhost:8080
    database: ecoinvent_391_cutoff
```

This registry decouples the `db_ref.source` short name from the actual
connection details, so recipe cards stay portable.

If the `databases` section is omitted, a single default database (the
currently running gdt-server) is assumed for all `db_ref` lookups.

---

## Implementation Plan

### Phase 1 — Database Registry and Connection Layer

**File:** `lca_engine.py` (new helper class)

1. Parse the `databases` section from the recipe YAML.
2. Build a `DatabaseRegistry` dict: `{name -> RestClient}`.
3. If no `databases` section, use the existing default `RestClient`.
4. Add a helper `get_background_client(source_name)` that returns the right
   client or raises a clear error.

No recipe card changes needed yet; this is pure infrastructure.

---

### Phase 2 — Background Process Resolver

**File:** `lca_engine.py` (new method `_resolve_background_process`)

```
_resolve_background_process(client, process_name_or_uuid, allocation)
  → dict { flow_name: { amount, unit, type } }   # per-unit LCI of that process
```

Steps inside the resolver:

1. Query the background database for the named process (`GET /data/processes`
   filtered by name, or direct UUID lookup).
2. If the process is multi-output, apply the requested allocation method to
   reduce it to a single-output equivalent.
3. Run a unit-process LCI calculation on it (or read stored LCI if available).
4. Return a flat dict of elementary flows (emissions + resources) normalised
   to 1 unit of the process's reference output.

The resolver caches results keyed on `(source, process_name, allocation)` to
avoid repeated network calls within a single `run_analysis()` call.

---

### Phase 3 — Integration into Process Building

**File:** `lca_engine.py` → `_create_process()` (or equivalent)

When iterating over `process.inputs`:

```python
for inp in process.get("inputs", []):
    if "db_ref" in inp:
        bg_lci = resolver.resolve(
            source=inp["db_ref"]["source"],
            process=inp["db_ref"]["process"],
            allocation=inp["db_ref"].get("allocation", "none"),
        )
        scale = inp["amount"]   # amount of this input per reference output
        # Add scaled elementary flows directly to this process's B-matrix column
        for flow_name, flow_data in bg_lci.items():
            add_to_biosphere(process_obj, flow_name, flow_data["amount"] * scale, flow_data["unit"])
        # Do NOT add inp["flow"] to the A-matrix (cut-off)
    else:
        # Existing behaviour — foreground technosphere link
        add_to_technosphere(process_obj, inp)
```

---

### Phase 4 — Transparency: Annotated LCI Output

When `db_ref` inputs are present, the output dict should include a
`background_contributions` section so the user can see where numbers came from:

```json
"background_contributions": {
  "P2 — Cotton farming": {
    "Electricity, US grid (0.45 kWh)": {
      "source": "uslci",
      "process": "Electricity, at grid, US",
      "scaled_flows": {
        "Carbon dioxide": { "amount": 0.312, "unit": "kg" },
        "Sulfur dioxide": { "amount": 0.0009, "unit": "kg" }
      }
    }
  }
}
```

This lives alongside the existing `lci` key and is optional (only present when
db_ref inputs exist).

---

### Phase 5 — Recipe Card Validation

**File:** `lca_engine.py` or a new `lca_validator.py`

Add validation at parse time (before touching any database):

- If `db_ref` present on an input, require `db_ref.source` and `db_ref.process`.
- If `db_ref.source` names a database not listed in `databases`, raise a clear
  error pointing to the missing registry entry.
- Warn (don't fail) if the `flow` name on a db_ref input doesn't match the
  reference output of the resolved background process.

---

### Phase 6 — SVG Visualization Update

**File:** `lca_svg.py`

Database-backed inputs should render differently from foreground inputs:

- Dashed border box (or different color fill) for the "virtual" background
  process node.
- Label showing `db_ref.source` and abbreviated process name.
- Arrow from the background box into the foreground process, labelled with
  the amount and unit.

This makes it visually obvious to students which numbers came from the recipe
card vs. which were looked up.

---

### Phase 7 — Bundle Generation Update

**File:** `generate_bundles.py`

The bundler already runs `run_analysis()` and stores results as JSON. No
structural change needed — the new `background_contributions` key will be
included automatically once Phase 4 is done.

However, bundles that contain `db_ref` inputs are **database-dependent**. The
bundler should record which database sources were used and at what version, so
stale bundles can be detected:

```json
"bundle_metadata": {
  "generated_at": "2026-06-20T...",
  "database_versions": {
    "uslci": { "name": "uslci_corr", "version": "2023-07-01" }
  }
}
```

---

## Recipe Card Example (After Extension)

```yaml
name: "Electricity-Intensive Process — 1 kg output"
goal: "Demonstrates database-backed electricity input"

databases:
  uslci:
    type: olca_gdt
    url: http://localhost:8080
    database: uslci_corr

lcia:
  method_name: TRACI 2.2

functional_unit:
  description: 1 kg of product
  amount: 1.0
  unit: kg

units:
  kg: Mass
  kWh: Energy

products:
  - { name: Product, unit: kg }
  - { name: Electricity, US grid, unit: kWh }

elementary_flows:
  emissions:
    - { name: Carbon dioxide, compartment: air, unit: kg }

processes:
  - name: P1 — Manufacturing
    reference_output: { flow: Product, amount: 1.0, unit: kg }
    inputs:
      # Foreground input with hand-authored numbers (unchanged)
      - { flow: Raw material A, amount: 0.8, unit: kg }

      # Background input — pulls all emissions from USLCI
      - flow: Electricity, US grid
        amount: 0.45
        unit: kWh
        db_ref:
          source: uslci
          process: "Electricity, at grid/US"

    # Direct emissions still hand-authored
    emissions:
      - { flow: Carbon dioxide, amount: 0.05, unit: kg }

reference_process: P1 — Manufacturing
```

---

## What Does NOT Change

- The existing foreground-only recipe card format is **fully backward
  compatible**. `db_ref` is opt-in per input.
- The gdt-server and `lca_methods` database are unchanged; the new feature
  adds connections to *additional* databases.
- LCIA characterization still comes from `lca_methods` regardless of which
  inventory database supplies the emissions.
- The matrix algebra (`A⁻¹ f`) is unchanged; `db_ref` inputs just contribute
  extra rows to the B-matrix column rather than a row in the A-matrix.

---

## Open Questions / Decisions Needed

1. **Cut-off vs. linked-process**: Should `db_ref` inputs be grafted into the
   B-matrix directly (cut-off, simpler) or should they be added as actual
   linked processes in the A-matrix (full system expansion, more accurate but
   harder to explain to students)? Recommendation: **cut-off first**, with
   a flag to opt into full linking later.

2. **Which background databases to support initially?** Options: USLCI only,
   or also Ecoinvent, or a custom flat-file library? Recommendation: **USLCI
   first** since it's free and well-supported by openLCA.

3. **Allocation default**: When a background process is multi-output, what
   allocation method should be the default? Recommendation: `none` (cut-off
   allocation) consistent with how Ecoinvent cutoff system model works.

4. **Offline / bundled fallback**: Should the bundler be able to pre-resolve
   all `db_ref` lookups and embed the results in the bundle JSON so the recipe
   can run offline without a background database? Recommendation: **yes** —
   add a `resolved_background` section to the bundle that caches the scaled
   flows, with a flag `db_ref_resolved: true` so the engine skips the live
   lookup when running from a bundle.

---

## File Change Summary

| File | Change |
|------|--------|
| `lca_engine.py` | Add `DatabaseRegistry`, `BackgroundProcessResolver`, modify `_create_process` to handle `db_ref` |
| `lca_svg.py` | Render db_ref inputs as dashed/shaded background nodes |
| `generate_bundles.py` | Record `database_versions`; support pre-resolved background flows |
| `case_studies/*.md` | (Optional) Add `databases:` section and `db_ref` fields to inputs |
| New: `lca_validator.py` | Schema validation for `db_ref` fields before computation |
