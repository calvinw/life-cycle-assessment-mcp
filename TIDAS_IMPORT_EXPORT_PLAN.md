# TIDAS JSON Import/Export — shipped

Bidirectional TIDAS JSON interchange between PRISM and the Tiangong LCA
platform, for [`calvinw/life-cycle-assessment-mcp`](https://github.com/calvinw/life-cycle-assessment-mcp).

Last updated: 2026-09-16

## Status: shipped and verified end-to-end with real Tiangong data

Both directions are implemented, tested, and confirmed against the real
Tiangong platform (not just schema samples):

- **Tiangong → PRISM** (`lca_core/interchange/tidas.py`, `preview_tidas()`):
  imports a real Tiangong Task Center export, including one with a
  populated `lifecyclemodels/` entry (Model graph-flattening verified
  against real data, not just schema samples).
- **PRISM → Tiangong** (`lca_core/interchange/tidas_export.py`,
  `export_tidas()`): generates a TIDAS JSON ZIP that **passed Tiangong's
  own server-side validation** (`VALIDATION_FAILED` → 86 → 41 → 24 → 20 → 4
  → accepted, across iterative rounds against the real platform) and was
  successfully imported into a live Tiangong account.
- **Full round trip confirmed**: PRISM bundle → `export_tidas()` → uploaded
  to Tiangong → accepted → exported back from Tiangong → re-imported via
  `preview_tidas()` → data intact (see
  `tests/fixtures/tidas_tiangong_export_with_model.zip`, a real Tiangong
  export containing the data from that round trip).
- Wired into the same dispatch used by openLCA JSON-LD and ILCD/eILCD:
  `preview_interchange()` / `export_interchange()`, plus the existing HTTP
  routes (`POST /api/interchange/import/openlca`,
  `POST /api/interchange/export` with `"format": "tidas-json"`) — no new
  routes, no frontend changes needed.
- `tests/test_tidas_interchange.py` (43 tests) plus TIDAS cases in
  `tests/test_interchange_route.py` cover both directions, both real
  fixtures, and the specific schema quirks documented below.

**For the detailed, field-level record of what Tiangong's schema actually
requires (and the mistakes made getting there) — including numeric field
types, per-type classification code tables, and the `review`/`compliance`
required-field sets — see [`docs/tidas_schema_alignment_notes.md`](./docs/tidas_schema_alignment_notes.md).
That document is the one to update when extending the exporter; treat the
sections below as the historical record of how the import side and the
format itself were first understood.**

## Known remaining gaps

- `source`/`contact` classification placeholders in `tidas_export.py`'s
  `_CATEGORY_ROOT` are read from the real `tidas_sources_category.json` /
  `tidas_contacts_category.json` tables but have never been exercised by an
  actual Tiangong validation report (no test bundle has included
  source/contact data). Revisit if/when that changes.
- `GlobalReferenceType`'s enum has no `"life cycle model data set"` member —
  `tidas_export.py`'s `_reference()` raises `UNSUPPORTED_TIDAS_REFERENCE_TYPE`
  loudly if anything ever tries to generate a reference pointing at a Model,
  rather than silently emitting data that would fail Tiangong's validation.
  Nothing in this codebase currently does that.
- Classification placeholders are exactly that — placeholders. Every
  dataset without real classification data gets tagged with a fixed,
  schema-valid-but-semantically-wrong category (e.g. a Process with no real
  classification is tagged "Agriculture, forestry and fishing" in ISIC).
  There is no attempt to map PRISM's own free-text classification data onto
  Tiangong's real category tables — see `_classification()`'s docstring in
  `tidas_export.py`.

## Goal (as originally scoped — see Status above for what shipped)

Let a user download a TIDAS export ZIP from the Tiangong platform's Task Center and import it directly into PRISM through the same import flow already used for openLCA JSON-LD and ILCD/eILCD packages — no manual conversion step. (Export was added later, once the ILCD-export-covers-PRISM→Tiangong assumption below turned out to be wrong — see "Known blocker" section, which is now resolved by shipping a real TIDAS JSON exporter instead.)

## Verified facts (not assumptions)

Everything below was confirmed either from Tiangong's actual documentation, from real TIDAS JSON schema samples, or — most importantly — from **inspecting a real Tiangong Task Center export ZIP file** (`tests/fixtures/tidas_tiangong_export.zip`). Nothing here is inferred from docs alone anymore.

### Tiangong platform behavior (`docs.tiangong.earth/en/docs/user-guide/tidas-zip-workflows/`)

- Import accepts: **"EcoSpold1, EcoSpold2, SimaPro CSV, openLCA JSON-LD, openLCA process XLSX, and ILCD/eILCD inputs"**
- Export: asynchronous job via Task Center → download one `.zip`.
- Web upload requirement: **"Place the TIDAS package contents at the ZIP root for web upload"** — confirmed true of the real export (no top-level wrapper folder).
- Local `tidas` CLI can convert TIDAS JSON ↔ eILCD XML offline, but that's a separate manual tool, not part of the platform's web upload/download flow.

### Real export ZIP layout — confirmed, not inferred

`tests/fixtures/tidas_tiangong_export.zip` (a real "Current user data" scope export) contains:

```text
manifest.json                              # authoritative index — see below
contacts/<uuid>_<version>.json             (3 files)
sources/<uuid>_<version>.json              (3 files)
unitgroups/<uuid>_<version>.json           (4 files)
flowproperties/<uuid>_<version>.json       (4 files)
flows/<uuid>_<version>.json                (31 files)
processes/<uuid>_<version>.json            (18 files)
```

No `lifecyclemodels/` folder is present in this export (0 in `manifest.json`'s `counts`), so the graph-flattening path is **not yet verified against a real file** — treat it as inferred-from-schema-sample until a sample with a populated `lifecyclemodels/` folder is available.

**Filenames include the version**: `<uuid>_<version>.json`, not a bare `<uuid>.json` like the ILCD folder convention. `version` matches ILCD's `common:dataSetVersion` (e.g. `00.00.001`, `01.01.003`).

**`manifest.json` is a reliable, authoritative index** — do not discover datasets purely by walking folders when a manifest is present. Real structure:

```json
{
  "format": "tiangong-tidas-package",
  "version": 2,
  "exported_at": "2026-09-16T15:13:02.181094898+00:00",
  "scope": "current_user",
  "roots": [{"table": "flowproperties", "id": "...", "version": "00.00.001"}, ...],
  "entries": [
    {
      "table": "contacts",
      "id": "97f476bd-415a-4463-955a-019202b70ae4",
      "version": "01.01.003",
      "file_path": "contacts/97f476bd-415a-4463-955a-019202b70ae4_01.01.003.json",
      "rule_verification": true
    },
    ...
  ],
  "counts": {"contacts": 3, "flowproperties": 4, "flows": 31, "lifecyclemodels": 0, "processes": 18, "sources": 3, "unitgroups": 4},
  "total_count": 63
}
```

Use `entries[].file_path` directly rather than re-deriving paths from `table`/`id`/`version` — it's already correct and avoids a class of encoding bugs.

### TIDAS JSON dataset structure — confirmed from the real export

TIDAS JSON is a **Badgerfish-style JSON encoding of the same ILCD XML schema** PRISM already imports/exports — not a distinct semantic model. Confirmed both from the official `tidas-example-*.json` samples in `tiangong-lca/tidas-sdks` and, more importantly, from the real exported `processes/*.json` and `flows/*.json` files:

- Root key is the same as the ILCD XML root element: `flowDataSet`, `processDataSet`, etc.
- XML attributes become JSON keys prefixed with `@` (e.g. `@refObjectId`, `@dataSetInternalID`, `@xml:lang`).
- XML namespace prefixes are preserved as literal key prefixes (`common:UUID`, `common:shortDescription`) rather than being resolved/stripped.
- Element text content becomes `#text` when the element also carries attributes or is part of a multilingual list; a plain-text-only leaf may appear as a bare string.
- Repeated elements become JSON arrays; a single occurrence may appear as a bare object instead of a one-item array — **converters must handle both shapes** (confirmed: real `flowProperties.flowProperty` appears as a bare object when there's exactly one).
- Field names inside `exchanges.exchange[]` (`meanAmount`, `resultingAmount`, `exchangeDirection`, `referenceToFlowDataSet.@refObjectId`/`@type`/`@uri`/`@version`, `dataSetInternalID`, `dataDerivationTypeStatus`) are **identical** to the ILCD XML fields `lca_core/interchange/ilcd.py` already parses.
- **Numeric fields are inconsistently typed**: the official schema sample has `"meanValue": "1.0"` (string), but the real export has `"meanAmount": 1` (JSON number). **The converter must accept both `str` and `int`/`float` for every numeric field** — do not assume one JSON type.
- Reference URIs in the real export point to `.json` (e.g. `"@uri": "../flows/47b11e0e-....json"`), not `.xml` like the official ILCD-style samples. **Don't parse or resolve `@uri` at all** — resolve references only via `@refObjectId` against the manifest/dataset-by-id map, exactly like `ilcd.py` already does. This sidesteps the `.json` vs `.xml` inconsistency entirely.

### A Tiangong-specific vendor extension is present and must be tolerated

The real export contains a namespace Tiangong adds itself when it imports data from another tool:

```json
"common:other": {
  "@xmlns:tidasimport": "https://tiangong.earth/tidas/import-trace/1.0",
  "tidasimport:sourceTrace": {"@marker": "TIDAS_IMPORT_TRACE_V1", "payload": {...}},
  "tidasimport:conversionGap": {
    "@marker": "TIDAS_IMPORT_GAP_V1",
    "detail": "process classification not derivable from source; pending ISIC assignment",
    "field": "classificationInformation.common:classification",
    "status": "unclassified-pending"
  }
}
```

This confirms the same rule the ILCD plan already established: **the importer must ignore unrecognized namespaces/attributes rather than require them**. `tidasimport:conversionGap` is a nice-to-have signal (Tiangong is telling us a field it couldn't populate) that could optionally surface as a PRISM warning, but is not required for a correct import.

**Consequence**: this is not a new field-mapping problem. It's a new *syntax* (Badgerfish JSON, with real-world quirks: mixed numeric types, `.json` URIs, a vendor extension) over an *already-solved* semantic mapping (ILCD → PRISM). The implementation should reuse `ilcd.py`'s reference-resolution, graph-flattening, and required-vs-warning logic rather than reimplementing it.

## Former blocker for the PRISM → Tiangong direction — superseded

This plan originally assumed PRISM → Tiangong needed no new format work
because Tiangong's docs list "ILCD/eILCD inputs" as accepted. In practice,
uploading a real `export_ilcd()` ZIP to Tiangong's Task Center "TIDAS
Import" flow failed with `"the package does not contain any supported TIDAS
datasets"` — that import path only recognizes TIDAS JSON, not ILCD XML,
regardless of ZIP layout (`ILCD/`-wrapped or flattened to root; both were
tried and both failed identically). That's what motivated building
`export_tidas()` as a real TIDAS JSON serializer instead of just fixing
`ilcd_export.py`'s packaging.

`ilcd_export.py`'s default output is still `ILCD/`-wrapped (unchanged, to
stay compatible with openLCA Desktop and the ILCD standard convention —
changing the default risked breaking round-trips through `ilcd.py`'s own
importer and other ILCD-consuming tools, for no benefit since Tiangong
doesn't accept ILCD XML at all). Instead, `ilcd.py`'s **importer** was made
more permissive: `preview_ilcd()` / `has_root_level_ilcd_layout()` now
accept a root-of-zip layout (no `ILCD/` wrapper) in addition to the
standard wrapped one, so a package built that way by some other tool can
still be read. This is a pure robustness addition with no change to
existing behavior — see `tests/test_ilcd_interchange.py`'s
`test_root_of_zip_layout_without_ilcd_wrapper_is_accepted`.

## Package structure Tiangong actually produces — confirmed

```text
manifest.json                              # authoritative index (table/id/version/file_path per dataset + counts)
processes/<uuid>_<version>.json            # processDataSet
flows/<uuid>_<version>.json                # flowDataSet
flowproperties/<uuid>_<version>.json       # flowPropertyDataSet
unitgroups/<uuid>_<version>.json           # unitGroupDataSet
sources/<uuid>_<version>.json              # sourceDataSet
contacts/<uuid>_<version>.json             # contactDataSet
lifecyclemodels/<uuid>_<version>.json      # lifeCycleModelDataSet — not present in the sample; folder name inferred by symmetry with `counts.lifecyclemodels` in manifest.json, not yet seen on disk
```

Contents sit at ZIP root exactly as documented, confirmed by unzipping the real fixture. This differs from openLCA Desktop's `ILCD/`-wrapped exports in two ways: no wrapper folder, and filenames carry `_<version>` suffixes.

## Format detection

```text
ZIP contains "olca-schema.json" at root                            → openLCA JSON-LD (existing)
ZIP contains a top-level "ILCD/" directory                         → ILCD/eILCD (existing)
ZIP contains "manifest.json" at root with
  manifest["format"] == "tiangong-tidas-package"                    → TIDAS JSON (new) — use this as the primary signal
Neither                                                             → UNSUPPORTED_PACKAGE_FORMAT (400)
```

Detecting via `manifest.json`'s `format` field (confirmed present and literally `"tiangong-tidas-package"` in the real export) is more robust than sniffing folder names, and doesn't risk colliding with the ILCD detection rule (which requires a top-level `ILCD/` directory) or the openLCA rule (`olca-schema.json`). Fall back to sniffing top-level dataset folders (`processes/`, `flows/`, etc.) only if a package claims to be TIDAS-shaped but lacks `manifest.json` — treat that as a warning-worthy degraded case, not the primary path.

## Implementation batches — all complete

### Batch A: Contract and fixtures — complete

- [x] Got a real exported ZIP from the Tiangong platform's Task Center. Checked in as `tests/fixtures/tidas_tiangong_export.zip` (63 datasets: 18 processes, 31 flows, 4 flow properties, 4 unit groups, 3 sources, 3 contacts, 0 life cycle models).
- [x] Confirmed the real export is flat at ZIP root, no wrapper folder.
- [x] Confirmed `manifest.json`'s exact shape (`format`, `version`, `exported_at`, `scope`, `roots`, `entries[]`, `counts`, `total_count`) and that `entries[].file_path` is directly usable.
- [x] Got a second real fixture with a populated `lifecyclemodels/` entry (`tests/fixtures/tidas_tiangong_export_with_model.zip`) — obtained by round-tripping synthetic data through the real platform. Graph-flattening is now verified against real data, not just schema samples.
- [x] Format-detection rule, folder/root-key mapping, and Badgerfish JSON quirks documented — see `docs/tidas_schema_alignment_notes.md` and the module docstrings in `tidas.py`/`tidas_export.py` rather than a separate contract doc (the separate-doc plan below wasn't followed; the notes ended up living closer to the code instead).

### Batch B: Core TIDAS JSON → PRISM converter — complete

- [x] `lca_core/interchange/tidas.py`: `preview_tidas(package: bytes) -> dict`, same response shape as `preview_openlca`/`preview_ilcd`.
- [x] `manifest.json` parsed first when present, with fallback to folder-name scanning (warns `TIDAS_MISSING_MANIFEST`) when absent.
- [x] Badgerfish-JSON navigation primitives (`_child`, `_children`, `_text`, `_attr`, `_first_descendant`, `_descendants`) mirroring `ilcd.py`'s `ElementTree`-based ones closely enough that the field-mapping logic reads almost identically between the two files.
- [x] References resolved via `@refObjectId` only, `@uri` never parsed.
- [x] `ilcd.py`'s field-mapping logic ported field-for-field.
- [x] Graph-flattening for `lifecyclemodels` — verified against real data (see Batch A).
- [x] Handles the extra `json_tg` top-level sibling key seen in real Tiangong exports (`_read_json_member` looks up the dataset root by name rather than assuming a single top-level key).
- [x] Reuses `archive.py`'s shared safety checks.
- [x] Tests in `tests/test_tidas_interchange.py` against both real fixtures.

### Batch C: Dispatch and HTTP routing — complete

- [x] TIDAS detection wired into `lca_core/interchange/importer.py`'s `preview_interchange()` (via `manifest["format"] == "tiangong-tidas-package"`) and `exporter.py`'s `EXPORT_FORMATS["tidas-json"]`.
- [x] No new routes — same `/api/interchange/import/openlca` and `/api/interchange/export` endpoints.
- [x] Frontend needs no changes: response shape identical across all three formats.
- [x] Tested through the real HTTP route (`tests/test_interchange_route.py`), including the export-filename-suffix bug that shipped once and was caught and fixed (`lca_server.py`'s `suffix` mapping only handled two of three formats).

### Batch D: Validation and hardening — complete

- [x] Missing optional folders tolerated.
- [x] Unmapped dataset types warn rather than fail.
- [x] Malformed JSON, missing UUID, duplicate IDs, empty packages all tested (`tests/test_tidas_interchange.py`).
- [x] Both Badgerfish shapes (bare object vs array) handled and tested.
- [x] Packages with and without `lifecyclemodels/` both tested against real fixtures.

## Export: not in the original plan, added and shipped anyway

The original plan (see git history) scoped this as import-only, on the
assumption that PRISM's existing ILCD export covered the PRISM → Tiangong
direction. That assumption was tested against the real platform and found
wrong (see "Former blocker" above), so `export_tidas()` was built as a real
TIDAS JSON serializer — `lca_core/interchange/tidas_export.py` — and pushed
through five rounds of real Tiangong server-side validation until accepted.
See `docs/tidas_schema_alignment_notes.md` for the field-level detail of
what that took and why it should have taken one round instead of five.

## Deferred / explicitly out of scope

- `tidas-sdk` Python package as a runtime dependency — not needed; the Badgerfish JSON shape is simple enough to parse/generate directly with the same approach as `ilcd.py`, avoiding a pre-1.0 external dependency (per PyPI, `tidas-sdk` is "currently in pre-1.0" and requires Python 3.12+, while this project targets 3.11+).
- EcoSpold, SimaPro CSV (Tiangong's other accepted import formats, not this engine's concern).
- LCIA method import.
- Persistent storage (import loads to workspace only, same as existing formats).
- Mapping PRISM's own classification data onto Tiangong's real category tables (see "Known remaining gaps" above) — current export uses fixed placeholders.

## References

- [`docs/tidas_schema_alignment_notes.md`](./docs/tidas_schema_alignment_notes.md) — the field-level record of Tiangong's actual schema requirements for export; start here when extending `tidas_export.py`
- [Tiangong TIDAS ZIP workflows doc](https://docs.tiangong.earth/en/docs/user-guide/tidas-zip-workflows/) — accepted import formats, export flow, root-of-zip requirement
- [tiangong-lca/tidas-spec](https://github.com/tiangong-lca/tidas-spec) `assets/tidas/schemas/*.json` — the authoritative JSON Schema files; read these directly rather than inferring from validation error messages
- [tidas-sdks test-data](https://github.com/tiangong-lca/tidas-sdks/tree/main/test-data) — official schema samples
- `tests/fixtures/tidas_tiangong_export.zip` — real Tiangong Task Center export, no Model
- `tests/fixtures/tidas_tiangong_export_with_model.zip` — real Tiangong Task Center export containing a populated `lifecyclemodels/` entry, obtained by round-tripping synthetic data through the live platform
- `tests/test_tidas_interchange.py`, `tests/test_interchange_route.py` — regression coverage for both directions
- [Existing ILCD Import Plan](./ILCD_IMPORT_PLAN.md) — the mapping and graph-flattening logic `tidas.py` ports
- [Existing Export Plan](./INTERCHANGE_EXPORT_PLAN.md) — dual-format export structure and `ilcd_export.py`
