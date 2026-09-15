# openLCA JSON-LD Import Implementation Plan

Prepared for [`calvinw/life-cycle-assessment-mcp`](https://github.com/calvinw/life-cycle-assessment-mcp) and the PRISM LCA data manager.

Last updated: 2026-09-15

## Status

The implementation is split into four independently reviewable batches. The first
release is a stateless, import-only workflow: importing means loading converted
datasets into the webapp workspace, not writing them to a database. Export is not
required for this release.

| Batch | Scope | Status | Codex-assisted active work |
| --- | --- | --- | --- |
| 1 | Import contract, field mapping, representative fixtures | Complete | Complete |
| 2 | openLCA JSON-LD to usable PRISM workspace bundle | Started; conversion baseline works, response refactor required | 2–4 hours |
| 3 | Stateless import HTTP route, CORS, limits, cleanup | Not started | 2–4 hours |
| 4 | Load imported bundles into the PRISM webapp workspace | Not started; belongs in the PRISM repository | 2–6 hours |

Estimated remaining implementation time with Codex GPT-5.6 Sol is approximately
6–14 hours of active work. This is roughly one focused working day when both
repositories and representative fixtures are available. Allow up to two elapsed
working days when manual openLCA Desktop verification or frontend integration
feedback requires another iteration. This is an engineering estimate, not a
model completion-time guarantee.

### Work completed

- Added the transport-independent `lca_core.interchange` package.
- Added a stable `InterchangeError` error type.
- Added an openLCA JSON-LD ZIP-to-PRISM importer baseline.
- Added ZIP path traversal, symbolic-link, entry-count, compressed-size, and expanded-size checks during import.
- The current importer preserves source IDs and produces normalized PRISM records, but still returns the earlier flat preview/conflict shape.
- Added focused conversion tests.
- Verified all 77 records in the current PRISM seed snapshot:
  - 10 Models
  - 18 Processes
  - 31 Flows
  - 4 Flow Properties
  - 4 Unit Groups
  - 10 Sources
- Verified that a real-data JSON-LD package can be read by the official `olca-schema` Python reader.

An export baseline and its lossless PRISM extension also exist in the repository,
but they are adjacent work and are not part of the first import release or its
completion criteria. The importer may continue to recognize that extension for
backward compatibility.

### Current files

```text
lca_core/interchange/
├── __init__.py
├── errors.py
└── openlca.py

docs/openlca_interchange_contract.md
tests/test_openlca_interchange.py
```

### Remaining work in the current core batches

- Test import using packages exported by the openLCA desktop application, rather than only engine-generated packages.
- Add graph tests with multiple Processes and Process Links.
- Add tests for edited openLCA packages, missing references, duplicate IDs, unsupported entity types, and malformed entity documents.
- Replace the legacy `catalog`, `decision`, `matches`, and flat preview-row response with the workspace-bundle contract defined below.
- Verify that an imported bundle can be loaded directly by the PRISM webapp and submitted to the existing calculation workflow without database persistence.
- Decide whether to keep the core converter in one module or split the import path into archive, mapping, reference, and validation modules before the HTTP batch.
- Document every field that cannot be represented directly in both systems.

## Goal

Allow a PRISM user to import an industry-relevant LCA exchange package into the
webapp and use it immediately. The first supported format is the openLCA schema
version 2 JSON-LD ZIP format.

The first release supports one operation: import an openLCA JSON-LD ZIP and return
a complete normalized PRISM dataset bundle that the webapp can use immediately.

Export and additional formats such as ILCD/eILCD and EcoSpold 2 can be added after
the openLCA import workflow is complete and validated. They are outside the first
release.

## Why openLCA JSON-LD is first

openLCA JSON-LD provides a useful balance between industry interoperability and implementation cost:

- openLCA can import and export the format.
- Packages use JSON documents in a documented ZIP layout.
- The schema includes Product Systems and Process Links, which can represent the PRISM Model graph.
- Its root entities map closely to the seven PRISM dataset types.
- It avoids implementing XML serialization and XSD handling in the first release.

This is an external openLCA exchange format. It is different from a private PRISM backup JSON format.

## Current systems

### PRISM data manager

- React, Vite, and TypeScript
- Static deployment on GitHub Pages
- Production origin: `https://catiehe.github.io`
- The existing persistent application has one `datasets` table for seven dataset types, but the first import release does not write to it:
  - `model`
  - `process`
  - `flow`
  - `flow_property`
  - `unit_group`
  - `source`
  - `contact`
- Each row contains `id`, `type`, `name`, `description`, and an ILCD-like JSON `payload`

### LCA engine

- Repository: `calvinw/life-cycle-assessment-mcp`
- Production service: `https://lca-mcp.mathplosion.com`
- Transport-independent logic under `lca_core`
- MCP and REST adapters in `lca_server.py`
- REST calculations are stateless
- Existing REST endpoints accept JSON and require no authentication
- Existing browser CORS origins do not include the PRISM production origin
- Current production Python version is 3.11

## System boundary

```text
PRISM GitHub Pages
  - import file picker and upload progress
  - imported-workspace preview
  - in-memory browser workspace used for viewing, editing, and calculation

LCA engine
  - openLCA package detection and safety checks
  - openLCA-to-PRISM field mapping
  - reference and graph validation
  - temporary-file management
```

The engine does not permanently store uploaded or generated packages. The first
release also does not persist imported data to Supabase. The browser receives a
complete workspace bundle and can use it immediately; refresh/reopen persistence
is explicitly outside this release.

## Dataset mapping

| PRISM type | openLCA root entity | ZIP folder |
| --- | --- | --- |
| `model` | `ProductSystem` | `product_systems/` |
| `process` | `Process` | `processes/` |
| `flow` | `Flow` | `flows/` |
| `flow_property` | `FlowProperty` | `flow_properties/` |
| `unit_group` | `UnitGroup` | `unit_groups/` |
| `source` | `Source` | `sources/` |
| `contact` | `Actor` | `actors/` |

A supported input ZIP contains a root manifest and one JSON document per dataset:

```text
olca-schema.json
product_systems/<uuid>.json
processes/<uuid>.json
flows/<uuid>.json
flow_properties/<uuid>.json
unit_groups/<uuid>.json
sources/<uuid>.json
actors/<uuid>.json
```

The root manifest is:

```json
{"version": 2}
```

## Model and graph mapping

- openLCA `ProductSystem` becomes a PRISM Model.
- `ProductSystem.processes` become PRISM `processInstances`.
- `refProcess` and `refExchange` determine the PRISM reference Process and quantitative reference.
- `ProcessLink` entries become PRISM Model connections.
- Provider, consumer, Flow, and exchange references must resolve within the imported bundle.
- `targetAmount` contributes to the reference Process multiplication factor where representable.

Packages previously exported by this engine may contain a lossless PRISM extension:

```text
otherProperties.prismInterchange
```

The extension contains the original PRISM payload and a hash of the standard openLCA fields. The importer handles it as follows:

- If the standard fields are unchanged, the importer may restore the exact PRISM payload.
- If openLCA changed the entity, the hash differs and the importer rebuilds the PRISM payload from the edited standard fields.
- A stale extension produces a warning and never overrides edited openLCA content.

## Import workflow

```text
User selects an openLCA JSON-LD ZIP
  → browser uploads it to the engine
  → engine checks the ZIP and manifest
  → engine reads supported openLCA entities
  → engine maps them to normalized PRISM datasets
  → engine validates that the returned bundle is internally usable
  → PRISM loads the bundle into a temporary webapp workspace
  → user can inspect, edit, and calculate with the imported data
```

Import is complete when the webapp has loaded the returned bundle. No database
write or conflict-resolution step is required.

### Import endpoint

```http
POST /api/interchange/import/openlca
Content-Type: multipart/form-data

file=<openLCA JSON-LD ZIP>
```

Response:

```json
{
  "format": "openlca-json-ld",
  "valid": true,
  "summary": {
    "model": 1,
    "process": 5,
    "flow": 12,
    "flow_property": 2,
    "unit_group": 2,
    "source": 1,
    "contact": 1
  },
  "datasets": {
    "models": [],
    "processes": [],
    "flows": [],
    "flow_properties": [],
    "unit_groups": [],
    "sources": [],
    "contacts": []
  },
  "warnings": [],
  "errors": []
}
```

Each item in the grouped arrays uses the normal PRISM dataset shape (`id`, `type`,
`name`, `description`, and `payload`). IDs and internal references must already be
consistent when returned; the frontend must not need to remap them.

Unsupported openLCA entities such as Impact Methods, Currencies, Parameters,
Results, and DQ Systems are ignored with warnings in the first release. A missing
reference required to construct a usable Model, Process, Flow, Flow Property, or
Unit Group is a conversion error rather than a database conflict.

## Imported workspace lifecycle

The PRISM webapp owns the returned datasets in a temporary workspace. It may keep
them in React state and pass them to existing viewing, editing, and calculation
flows. Closing or refreshing the page may discard the workspace in
the first release.

Supabase persistence, IndexedDB persistence, merging with saved datasets, and
create/update/reuse/skip decisions are separate future features. They are not
requirements for the engine's import capability.

## Engine implementation structure

Current baseline:

```text
lca_core/interchange/
├── __init__.py
├── errors.py
└── openlca.py
```

The converter can be split before the HTTP batch if continued growth makes separate modules clearer:

```text
lca_core/interchange/
├── __init__.py
├── archive.py
├── errors.py
├── models.py
├── openlca_import.py
├── references.py
└── validation.py
```

HTTP routes in `lca_server.py` remain thin. They enforce limits, parse requests,
call `lca_core.interchange`, and serialize the response. Field mapping and archive
rules do not belong in the HTTP adapter.

## Browser access

Supabase authentication is not part of the first stateless release. Required
browser controls are:

1. Add `https://catiehe.github.io` to the exact CORS allowlist.
2. Keep explicit local development origins.
3. Allow `Content-Type` request headers.
4. Do not log uploaded dataset content.
5. Apply request-size, conversion-time, and concurrency limits to protect the public service.

Authentication or gateway-level access control can be added later without
changing the import bundle contract.

## Archive and resource safety

Initial configurable defaults:

- 25 MB compressed upload
- 250 MB total expanded content
- 5,000 archive entries
- 120-second conversion timeout
- A small global concurrency limit, with per-client limits if a reliable client identity is available

The engine rejects:

- absolute paths
- parent-directory traversal
- backslash-based paths
- symbolic links
- duplicate dataset IDs
- invalid UTF-8 or malformed JSON
- unsupported package manifest versions
- excessive file count or expanded size

HTTP upload code must enforce limits while receiving the request. It must not read an unlimited body into memory before checking size.

If a response streams from a temporary file, cleanup must run after the response finishes. A normal `finally` block cannot delete the file before streaming has completed.

## Error contract

Every non-file error uses a stable shape:

```json
{
  "error": {
    "code": "UNRESOLVED_DATASET_REFERENCE",
    "message": "Dataset '<id>' has an unresolved flow reference.",
    "details": {
      "dataset_id": "<id>",
      "reference_id": "<missing-id>",
      "path": "exchanges[0].referenceToFlowDataSet"
    }
  }
}
```

Status codes:

- `400`: malformed request, ZIP, manifest, or JSON
- `413`: compressed or expanded package exceeds limits
- `422`: valid request whose data or references cannot be converted
- `429`: rate or concurrency limit
- `500`: unexpected conversion failure
- `504`: conversion timeout

## Delivery batches

### Batch 1: import contract and fixtures

Status: complete.

- Define the openLCA schema version and ZIP layout.
- Define the seven dataset mappings.
- Define import graph, reference, error, and workspace-bundle contracts.
- Capture representative PRISM data from the current seed snapshot.
- Record import limitations and extension behavior.

### Batch 2: import workspace-bundle core

Status: started; baseline entity conversion works.

- Validate archive structure and manifest.
- Read all seven supported openLCA entity types.
- Normalize external openLCA entities into PRISM payloads.
- Restore exact PRISM payloads only when the extension hash is current.
- Remove the legacy catalog matching and persistence-oriented decision metadata from the public import result.
- Return grouped, internally consistent PRISM datasets, counts, and warnings.
- Verify that the result can be consumed directly by PRISM viewing and calculation flows.
- Test packages created and edited by openLCA desktop.

### Batch 3: engine HTTP integration

Status: not started.

- Add the PRISM production CORS origin and required headers.
- Add multipart upload support.
- Add the stateless import route.
- Add upload streaming limits, concurrency limits, timeout, and cleanup.
- Add HTTP and security tests.

### Batch 4: PRISM temporary-workspace integration

Status: not started.

- Add import file selection and upload progress.
- Load returned datasets into the webapp's workspace state.
- Add counts, warnings, errors, and record details.
- Verify imported Models can be viewed, edited, and calculated.
- Add an end-to-end import report.

Persistent storage and merging with saved datasets are deferred and must not
block this batch.

## Required tests

### Import tests

- A valid openLCA package produces the expected normalized counts.
- A package containing a current PRISM extension restores its payload without loss.
- The returned grouped bundle has stable IDs and fully resolved required references.
- The PRISM webapp can use the bundle without a database lookup or ID-remapping step.
- An openLCA-edited entity ignores a stale PRISM extension.
- Unsupported root types produce warnings.
- References required by PRISM Models, Processes, Flows, Flow Properties, or Unit Groups cause a structured conversion error.
- References belonging only to unsupported or intentionally omitted openLCA entities produce warnings.
- Broken ZIP, malformed JSON, duplicate IDs, unsafe paths, symbolic links, and oversized packages are rejected.

### HTTP tests

- PRISM production CORS preflight succeeds.
- Unapproved origins receive no allow-origin header.
- Upload, timeout, and concurrency limits are enforced.
- Temporary files are deleted after successful and failed requests.

### End-to-end acceptance

1. Export a known multi-Process Product System from openLCA Desktop.
2. Upload that package through the PRISM import endpoint.
3. Confirm the engine reconstructs the expected Processes, Flows, units, quantitative references, and Model connections.
4. Load the reconstructed Model and references into a temporary webapp workspace.
5. View the graph and run a calculation without reading or writing Supabase.
6. Compare the PRISM graph and calculation semantics with the source Product System.

## Completion criteria

The first release is complete when:

- A user can upload an openLCA ZIP and load the normalized bundle directly into the PRISM webapp workspace.
- Imported Models can be inspected, edited, and calculated without database persistence.
- Missing or ambiguous references are reported clearly and never produce a silently broken workspace.
- The engine retains no uploaded or generated files after the response completes.
- CORS, archive safety, resource-limit, and cleanup tests pass.
- An openLCA Desktop Product System retains its supported graph and calculation semantics after import into PRISM.

## Deferred work

The following work is intentionally outside the first release:

- PRISM-to-openLCA export UI and HTTP delivery
- Export acceptance testing in openLCA Desktop
- Supabase or IndexedDB persistence
- Merging imported records with saved datasets
- Import conflict decisions and atomic database writes
- Additional exchange formats such as ILCD/eILCD and EcoSpold 2
