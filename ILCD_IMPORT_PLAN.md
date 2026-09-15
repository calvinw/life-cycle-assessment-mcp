# ILCD/eILCD Import Implementation Plan

Extends the openLCA JSON-LD import work in `ENGINE_IMPORT_EXPORT_PLAN.md` to a
second package format. Read that document first — this one only covers what's
different for ILCD.

Last updated: 2026-09-15

## Status

Batch A is complete. Batches B–D are not started; no converter code exists
yet.

A real sample package (`tests/fixtures/ilcd_plastic_broom.zip`, an
openLCA-Desktop ILCD export of a mock product system, originally provided as
`Plastic Broom.zip`) was inspected while writing this plan and is now checked
into the repo. Unlike the openLCA JSON-LD work, which had no real-world
fixture, **this format already has one** — every rule below is grounded in
that real file, not speculation.

| Batch | Scope | Depends on | Status |
| --- | --- | --- | --- |
| A | Format detection, field mapping, contract doc | Nothing new | Complete |
| B | Core ILCD XML → PRISM converter | A | Not started |
| C | Wire into the existing HTTP route (no new route) | B | Not started |
| D | Real-world hardening (missing folders, warnings, tests) | C | Not started |

### Work completed (Batch A)

- Checked in the real sample as `tests/fixtures/ilcd_plastic_broom.zip`.
- Wrote `docs/ilcd_interchange_contract.md`: format-detection rule, the
  seven-type folder/root-element mapping, XML namespace-handling rules, the
  required-vs-warning reference boundary (deliberately narrower than the
  openLCA JSON-LD contract's, justified by a gap found in the real sample),
  and the Model/graph flattening rule.
- No code yet — Batch B starts the actual `lca_core/interchange/ilcd.py`
  module.

Rough estimate: comparable to the openLCA JSON-LD core converter itself
(6–14 hours per that plan's estimate for Batches 1–2), not to the small
HTTP-wiring step done on top of it. ILCD's XML field names already match
PRISM's stored payload shape closely (see below), which should offset some of
the added cost of XML parsing versus semantic field remapping.

## Goal

Let the same import endpoint also accept an ILCD/eILCD XML ZIP export — the
other format openLCA Desktop (and other LCA tools) can produce — and return
the identical PRISM dataset bundle shape the openLCA JSON-LD path already
returns.

## Why this should need zero frontend changes

PRISM's own dataset `payload` is already ILCD-shaped JSON (see "PRISM data
manager" in the sibling plan: "an ILCD-like JSON `payload`"). The frontend
(`catiehe/tiangong-simple`) already calls one endpoint
(`POST /api/interchange/import/openlca`) and renders whatever
`summary`/`datasets`/`warnings`/`errors` come back, using the seven PRISM
dataset types as the grouping key — it does not know or care which source
format produced them.

So the plan is:

- Keep the route name and response contract exactly as they are.
- Have the engine sniff the uploaded ZIP and dispatch to the openLCA JSON-LD
  reader (existing) or the new ILCD reader (new) based on what's inside.
- Both readers return the same normalized PRISM rows.

If this holds, the frontend needs no changes at all — the existing
`importOpenLcaPackage()` call and `ImportOpenLca.tsx` page work unmodified for
either format. Confirm this stays true once Batch C is built; if warning/error
codes turn out to need format-specific handling, that's a frontend change to
flag, not something to assume away.

### Format detection

```text
zip contains "olca-schema.json" at root         → openLCA JSON-LD (existing)
zip contains a top-level "ILCD/" directory       → ILCD/eILCD (new)
neither                                          → UNSUPPORTED_PACKAGE_FORMAT (400)
```

## What the real sample showed

`tests/fixtures/ilcd_plastic_broom.zip` (openLCA Desktop → File → Export → ILCD) contained:

```text
ILCD/flows/<uuid>.xml            (6 files)
ILCD/processes/<uuid>.xml        (4 files)
ILCD/unitgroups/<uuid>.xml       (4 files)
ILCD/lifecyclemodels/<uuid>.xml  (1 file  — this is the Model/ProductSystem equivalent)
ILCD/lciamethods/<uuid>.xml      (2 files — out of scope, same as openLCA Impact Methods)
```

No `flowproperties/`, `sources/`, or `contacts/` folders at all — openLCA's
ILCD export appears to omit folders with nothing to put in them, rather than
emitting an empty directory. **The importer must not require these folders to
exist.**

### Field mapping is structurally close to PRISM's payload already

A real flow XML (`ILCD/flows/03f77556-....xml`):

```xml
<f:flowDataSet>
  <f:flowInformation>
    <f:dataSetInformation>
      <common:UUID>03f77556-...</common:UUID>
      <f:name><f:baseName xml:lang="en">Mock electricity, medium voltage</f:baseName></f:name>
    </f:dataSetInformation>
    <f:quantitativeReference>
      <f:referenceToReferenceFlowProperty>0</f:referenceToReferenceFlowProperty>
    </f:quantitativeReference>
  </f:flowInformation>
  <f:modellingAndValidation><f:LCIMethod><f:typeOfDataSet>Product flow</f:typeOfDataSet></f:LCIMethod></f:modellingAndValidation>
  <f:administrativeInformation>...</f:administrativeInformation>
  <f:flowProperties/>
</f:flowDataSet>
```

Compare to PRISM's already-stored `flow` payload shape (from
`tests/test_openlca_interchange.py`): `flowInformation.dataSetInformation.name.baseName`,
`flowInformation.quantitativeReference.referenceToReferenceFlowProperty`,
`modellingAndValidation.typeOfDataSet`, `flowProperties`. **These are the same
keys.** The ILCD converter is mostly "turn this XML element into a dict with
the same key names," not the semantic remapping the openLCA JSON-LD converter
needed (`@type` → `type`, `refObjectId` → PRISM reference shape, etc.).

### The Model/graph mapping is the hard part, same as it was for openLCA

The `lifecyclemodels` XML (ILCD's equivalent of a Model) represents Process
Links very differently from PRISM's flat `connections: [{fromInstanceId,
toInstanceId}]` list:

```xml
<model:processInstance dataSetInternalID="1" multiplicationFactor="0.0">
  <model:referenceToProcess refObjectId="3ddfacfd-..." .../>
  <model:connections>
    <model:outputExchange flowUUID="03f77556-...">
      <model:downstreamProcess id="0" flowUUID="03f77556-..." ns10:linkedExchange="2"/>
      <model:downstreamProcess id="2" flowUUID="03f77556-..." .../>
    </model:outputExchange>
  </model:connections>
</model:processInstance>
```

Connections are nested inside the *upstream* process instance rather than
listed flat. Converting this to PRISM's flat connection list needs the same
kind of graph-flattening work the openLCA `ProcessLink` → PRISM connection
mapping already required — expect this to be the single largest piece of
Batch B.

### A vendor extension namespace is present and must be tolerated

Both the flow and lifecycle-model XML declare
`xmlns:ns10="http://openlca.org/ilcd-extensions"` and use it for attributes
like `ns10:origin="openLCA"` and `ns10:linkedExchange="3"`. A spec-strict
ILCD file from a different tool won't have this namespace at all. **The
importer must ignore unrecognized namespaces/attributes rather than require
them** — `ns10:linkedExchange` may be a useful hint for resolving which
exchange a connection targets when present, but cannot be relied on.

### Missing optional references must warn, not fail

This sample has no `flowproperties/` folder, yet flows declare
`referenceToReferenceFlowProperty`. Whatever that resolves to (an inline
`flowProperties` element, in this sample an empty one, or nothing) needs
graceful handling: if a flow's declared reference can't be resolved, that's a
warning-worthy gap for a dataset that's still usable, not necessarily a hard
`UNRESOLVED_DATASET_REFERENCE` error — decide the exact boundary in Batch A
using the same required-vs-optional distinction the openLCA plan already
draws.

## Delivery batches

### Batch A: contract and fixtures — complete

- [x] Confirmed the ILCD → PRISM folder/type mapping (see table below and `docs/ilcd_interchange_contract.md`).
- [x] Checked in `tests/fixtures/ilcd_plastic_broom.zip` as the first real fixture — a genuine advantage over the openLCA JSON-LD work, which only had engine-generated fixtures at this stage.
- [x] Documented the format-detection rule and the required-vs-optional reference boundary.
- [x] Wrote `docs/ilcd_interchange_contract.md` with the mapping table and the namespace-tolerance / optional-folder-tolerance findings.

  | PRISM type | ILCD folder | ILCD root element |
  | --- | --- | --- |
  | `model` | `lifecyclemodels/` | `lifeCycleModelDataSet` |
  | `process` | `processes/` | `processDataSet` |
  | `flow` | `flows/` | `flowDataSet` |
  | `flow_property` | `flowproperties/` | `flowPropertyDataSet` |
  | `unit_group` | `unitgroups/` | `unitGroupDataSet` |
  | `source` | `sources/` | `sourceDataSet` |
  | `contact` | `contacts/` | `contactDataSet` |

### Batch B: core converter

- Add `lca_core/interchange/ilcd.py` (new module, mirrors `openlca.py`'s shape: a `preview_ilcd(package: bytes) -> dict` returning the exact same response shape `preview_openlca` returns).
- XML parsing: namespace-aware (`xml.etree.ElementTree` with an explicit namespace map, or `lxml` if already a dependency — check before adding a new one).
- Reuse the archive-safety checks from `openlca.py` (path traversal, entry count, compressed/expanded size) rather than reimplementing them — factor them out to a shared helper if they're not already generic.
- Flow/Process/UnitGroup conversion first (present in the real sample, testable immediately).
- FlowProperty/Source/Contact conversion next (not present in the sample — write against the ILCD schema directly, add a small fixture if a real one isn't available).
- Model/graph conversion last — flatten `lifecyclemodels`' nested `processInstance/connections/outputExchange/downstreamProcess` into PRISM's flat connection list.
- Tests against `tests/fixtures/ilcd_plastic_broom.zip`: expected counts (6 flows, 4 processes, 4 unit groups, 1 model, 0 flow properties/sources/contacts, 2 ignored `lciamethods` with warnings).

### Batch C: dispatch, no new route

- In the existing `/api/interchange/import/openlca` handler (or a shared helper both formats call), sniff the ZIP and call `preview_openlca` or `preview_ilcd` accordingly.
- Confirm the frontend needs no changes by testing `tests/fixtures/ilcd_plastic_broom.zip` through the real running route and the real deployed frontend (once Batch A/B of this plan and the pending openLCA deploy are both live).

### Batch D: hardening

- Warnings for `lciamethods/` and any other unmapped ILCD dataset type, matching the openLCA plan's treatment of Impact Methods/Currencies/etc.
- Tests for a package missing optional folders entirely (already true of the real sample — make sure this doesn't regress).
- Tests for malformed XML, missing `common:UUID`, and duplicate IDs (mirrors the openLCA plan's error-path tests).
- Decide whether to also accept `.xml` files that reference external resources by relative `uri` (seen in the flow sample's `referenceToDataSetFormat`) — likely out of scope; document it as deferred rather than silently ignoring it.

## Deferred / explicitly out of scope

- EcoSpold 2 (separate format, not covered by this plan).
- Resolving `uri`-based external references to files outside the ZIP.
- Anything already deferred in `ENGINE_IMPORT_EXPORT_PLAN.md` (export, persistence, conflict merging) — unchanged by adding a second import format.
