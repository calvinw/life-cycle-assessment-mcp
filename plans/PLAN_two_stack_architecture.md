# Plan: Two-Stack LCA Architecture

## Current State

The server already runs Stack 2 (EU/openLCA) minus one piece:

- `lca_biosphere` — openLCA LCIA Methods 2.8.0 flows (60,903 elementary flows) ✓
- LCIA methods — 547 categories: EF 3.1, ReCiPe, CML, TRACI 2.2, etc. ✓
- Background LCI database — **missing (BAFU)**

No background LCI database means product graphs can only model foreground
processes by hand. Every process's inputs and outputs must be written
explicitly in the product graph.

---

## Target Architecture

Two stacks, coexisting in the same Brightway project:

### Stack 1 — US (Federal LCA Commons)

| Component | Source | Status |
|---|---|---|
| Biosphere | `Federal_LCA_Commons-elementary_flow_list.zip` (332K FEDEFL flows) | Not yet imported |
| LCIA method | `Federal_LCA_Commons-TRACI_2_2.zip` (10 categories) | Not yet imported |
| LCI database | USLCI (1,341 processes) | Not yet imported |
| UUID consistency | USLCI ↔ FEDEFL: 98.5% match by UUID | — |

TRACI 2.2 impact categories: Global warming, Eutrophication (marine +
freshwater), Acidification, Smog, Ozone depletion, Particulate matter,
Cancer, Non-cancer, Freshwater ecotoxicity. Midpoint only, no endpoint/damage.

### Stack 2 — EU (openLCA)

| Component | Source | Status |
|---|---|---|
| Biosphere | openLCA LCIA Methods 2.8.0 (60,903 flows) | **Already loaded** |
| LCIA methods | openLCA LCIA Methods 2.8.0 (EF 3.1, ReCiPe, CML, etc.) | **Already loaded** |
| LCI database | BAFU (Swiss Federal LCI, ~12K processes) | Not yet imported |

EF 3.1 is the EU Environmental Footprint standard — what European LCA
courses and tutorials (e.g. the openLCA plastic broom tutorial) use.
ReCiPe adds endpoint/damage assessment (DALYs, species·yr, USD).

---

## What Each Stack Unlocks

Without a background LCI database, product graphs must model every upstream
process by hand. With one:

- A product graph can reference "Electricity, at grid" or "Transport, lorry"
  and get the real upstream emissions without modelling them explicitly
- Shorter, more realistic product graphs
- LCIA results include upstream impacts (e.g. electricity production's CO2)
- Scenario comparison: change one input, see how upstream impacts shift

---

## UUID Compatibility

Each stack has its own biosphere database with its own UUID set.
LCIA methods are imported matched against their stack's biosphere.
Mixing stacks in one calculation would break UUID matching and silently
zero contributions — the same bug we fixed in June 2026 for N2O.

| | Stack 1 biosphere | Stack 2 biosphere |
|---|---|---|
| Stack 1 LCIA methods | ✓ correct | ✗ wrong UUIDs |
| Stack 2 LCIA methods | ✗ wrong UUIDs | ✓ correct |
| USLCI exchanges | ✓ 98.5% match | ✗ ~0% match |
| BAFU exchanges | ✗ poor match | ✓ designed for this |

Product graphs declare their stack; the engine routes through the correct
biosphere and LCIA methods automatically.

---

## Product Graph Changes

Add one field to the YAML:

```yaml
stack: us   # Federal LCA Commons — TRACI 2.2 + USLCI
# or
stack: eu   # openLCA — EF 3.1 / ReCiPe + BAFU
```

Existing product graphs (cotton_fiber, polyester_tshirt, wool_yarn) default
to `eu` since they were built against the openLCA biosphere.

---

## Implementation Phases

### Phase 1 — Get Stack 2 fully working (fastest path)

Stack 2 is already 90% complete. The only missing piece is BAFU.

**BAFU import challenge:** BAFU distributes in zolca (openLCA binary format)
and EcoSpold 1. The EcoSpold 1 export from openLCA Desktop has schema
violations that cause `bw2io`'s strict parser to fail (discovered during
USLCI attempt — `firstAuthor` maxLength, `CASNumber` pattern errors).

Options for BAFU import:
- (a) Preprocess the EcoSpold 1 XML to fix schema violations, then use
  `SingleOutputEcospold1Importer`
- (b) Write a custom JSON-LD inventory importer (same approach considered
  for USLCI)
- (c) Check if BAFU is available on the openLCA Nexus in a cleaner format

Once BAFU is imported, `ProviderSearch` and the engine changes from
`IMPLEMENT_database_backed_technosphere.md` apply directly — no UUID
concerns since BAFU was designed for the openLCA biosphere.

### Phase 2 — Add Stack 1 (Federal LCA Commons)

1. Import `Federal_LCA_Commons-elementary_flow_list.zip` as `fedefl_biosphere`
2. Import `Federal_LCA_Commons-TRACI_2_2.zip` matched against `fedefl_biosphere`
3. Import USLCI JSON-LD with elementary flows matched to `fedefl_biosphere`
   by UUID (98.5% coverage) — no EcoSpold conversion needed
4. Add `stack:` field to product graph spec
5. Engine changes: `BIOSPHERE_DB` becomes per-stack, `_FLOW_INDEX` becomes
   a dict keyed by stack name, LCIA method filtering uses stack to avoid
   cross-contamination

### Phase 3 — Engine changes (applies to both stacks)

From `IMPLEMENT_database_backed_technosphere.md`:

- **`lca_provider_search.py`** — `ProviderSearch` class resolves product graph
  technosphere inputs against background databases. Foreground links win;
  background database consulted if no foreground provider; cut-off (not
  crash) if nothing found, reported in `unlinked_flows`.
- **`lca_engine.py`** — rewrite input-resolution loop to use `ProviderSearch`
- **`lca_validator.py`** — pre-run validation of `db_ref` fields
- **`lca_server.py`** — wire validation into `run_lca` tool

### Phase 4 — Repo cleanup

Delete stale gdt-server-era files (from `IMPLEMENT_database_backed_technosphere.md`
Phase 5): `Dockerfile.gdt`, `setup_olca.sh`, `start_olca.sh`,
`start_olca_ecoinvent.sh`, `stop_olca.sh`, `gdt_entrypoint.sh`,
`build_gdt_server.sh`, `docs/openlca_server_reference.md`, `generate_bundles.py`.

---

## Open Questions

1. **BAFU format**: Can BAFU be imported via preprocessed EcoSpold 1, or
   does it need a custom JSON-LD importer? Check openLCA Nexus for
   alternative export formats.

2. **Stack default**: Should product graphs without a `stack:` field default
   to `eu` (current biosphere) or require explicit declaration?

3. **ReCiPe endpoint**: ReCiPe (endpoint: DALYs, species·yr, USD) is in
   Stack 2's loaded methods. Once BAFU is imported, showing pre-computed
   ReCiPe results alongside TRACI 2.2 for existing case studies is a
   quick win for teaching damage assessment concepts.

4. **USLCI via JSON-LD**: Skip the EcoSpold conversion entirely. Parse
   the original JSON-LD zip from LCA Commons directly. Elementary flows
   match `fedefl_biosphere` at 98.5% by UUID — no name-based fuzzy
   matching needed.
