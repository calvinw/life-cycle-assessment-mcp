# Plan: BAFU JSON-LD Import (correct openLCA-compatible stack)

## Problem

The EcoSpold V1 import of BAFU:2026 gives wrong LCA results (0.276 vs 1.7 kg
CO₂-eq for the plastic broom tutorial) because EcoSpold V1 strips UUIDs and
forces name-based matching against biosphere3, which only has 4,709 flows.

## Root Cause

openLCA uses UUID-based flow matching internally. The correct stack is:

| Component | Source | Role |
|---|---|---|
| `olca_biosphere` | Parsed from openLCA LCIA Methods 2.8.0 zip | 60,903 elementary flows, UUID as code |
| `bafu` | BAFU:2026 **JSON-LD** from Nexus | 11k+ processes, flows referenced by UUID |
| LCIA methods | openLCA LCIA Methods 2.8.0 zip | CFs keyed to olca_biosphere UUIDs |

All three share the same UUID space — the same UUID space openLCA uses
internally. This is why the JSON-LD stack matches the video result.

## What We Already Have

- `olca_biosphere` — already built correctly (Step 1 from original import script)
- openLCA LCIA Methods 2.8.0 zip — already in `data/`
- openLCA LCIA methods — already imported (545 methods, Step 3)
- `import_bafu.py` — Step 1 and Step 3 still work; only Step 2 needs replacing

## What Needs To Change

### Step 1 — Re-download BAFU in JSON-LD format

On openLCA Nexus, download **BAFU:2026** as **JSON-LD** (not EcoSpold V1).
The JSON-LD zip contains folders like `processes/`, `flows/`, `flow_properties/`
etc. with `.json` files. Each process's biosphere exchanges reference flow UUIDs
directly.

Place it at: `data/bafu/BAFU-2026 v1_JSON-LD.zip` (or similar)

### Step 2 — Rewrite `import_bafu()` in `import_bafu.py`

Replace the lxml EcoSpold V1 parser with a JSON-LD parser:

```python
def import_bafu(bd, zip_path: pathlib.Path):
    # Parse processes/*.json from the JSON-LD zip
    # Each process has:
    #   process["@id"]         → code
    #   process["name"]        → name
    #   process["location"]    → location
    #   process["exchanges"]   → list of exchanges
    #     exchange["flow"]["@id"]  → flow UUID → (olca_biosphere, uuid) key
    #     exchange["amount"]       → amount
    #     exchange["isInput"]      → True = input (technosphere or biosphere)
    #     exchange["flowType"]     → "ELEMENTARY_FLOW" = biosphere
    #                                "PRODUCT_FLOW"    = technosphere/production

    # Linking is trivial: biosphere exchanges reference flow UUIDs directly,
    # and olca_biosphere codes ARE those UUIDs.
    # key = ("olca_biosphere", flow_uuid) — no name matching needed at all.
```

Key difference from EcoSpold V1: **zero name matching required**. Every
biosphere exchange in the JSON-LD already carries the UUID of its flow. We just
look it up in olca_biosphere by code.

### Step 3 — Fix idempotency sentinel (already done)

The sentinel `any(m[0] == "EF 3.1 Method (adapted)" for m in bd.methods)`
correctly identifies openLCA methods. No change needed.

### Step 4 — Delete stale databases and re-run

```bash
python3 -c "
import os; os.environ['BRIGHTWAY2_DIR'] = 'brightway_data'
import bw2data as bd; bd.projects.set_current('lca_server')
for name in ['bafu']:
    if name in bd.databases: del bd.databases[name]
"
python3 scripts/import_bafu.py
```

Expected result: 100% biosphere link rate (UUID matching), LCA result matching
the video (~1.7 kg CO₂-eq for the plastic broom).

## Validation

Run the plastic broom test after import:

```python
nylon6 = next(a for a in bd.Database('bafu')
              if a['name'] == 'Nylon 6, at plant' and a.get('location') == 'RER')
pla    = next(a for a in bd.Database('bafu')
              if a['name'] == 'Polylactide, granulate, at plant')

# Build broom: 0.03 kg nylon + 0.52 kg PLA
# Run LCA with ('EF 3.1 Method (adapted)', 'Climate change')
# Expected: ~1.7 kg CO₂-eq
```

Also check contribution breakdown matches video:
- PLA: ~82% of climate change
- Nylon: ~16%
- Transport: ~1.4%

## Current State of `data/` directory

```
data/
  bafu/
    BAFU-2026 v1_ecoSpold v1.zip     ← wrong format, keep for reference
    elementary_flows_mapping.csv      ← BAFU2BW crosswalk (no longer needed)
    BAFU-2026 v1_JSON-LD.zip          ← NEED TO DOWNLOAD THIS
  openLCA LCIA Methods 2.8.0 2025-12-15.zip  ← already present, correct
```

## Notes

- The EcoSpold V1 + biosphere3 path (current `import_bafu.py`) can stay as a
  fallback but gives ~6× underestimated climate change results.
- The BAFU2BW crosswalk CSV (`elementary_flows_mapping.csv`) is not needed for
  the JSON-LD path — UUID matching is exact and complete.
- `olca_biosphere` does NOT need to be rebuilt — it was built correctly from the
  LCIA Methods zip and already contains the right UUIDs.
- The openLCA LCIA methods also do NOT need to be re-imported.
- Only `bafu` needs to be deleted and reimported.
