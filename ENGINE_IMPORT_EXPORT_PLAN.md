# openLCA JSON-LD Import/Export Implementation Plan

Prepared for [`calvinw/life-cycle-assessment-mcp`](https://github.com/calvinw/life-cycle-assessment-mcp) and the PRISM LCA data manager.

Last updated: 2026-09-15

## Status

The implementation is split into five independently reviewable batches.

| Batch | Scope | Status | Estimate |
| --- | --- | --- | --- |
| 1 | Data contract, field mapping, representative fixtures | Complete | 0.5–1 day |
| 2 | PRISM bundle to openLCA JSON-LD export core | In progress; working baseline | 1–2 days |
| 3 | openLCA JSON-LD to PRISM import preview core | Started; round-trip baseline works | 1–2 days |
| 4 | HTTP routes, authentication, CORS, limits, cleanup | Not started | 1–2 days |
| 5 | PRISM UI and atomic Supabase persistence | Not started; belongs in the PRISM repository | 2–4 days |

Estimated total delivery time is 6–10 focused engineering days, including both repositories and end-to-end verification in openLCA.

### Work completed

- Added the transport-independent `lca_core.interchange` package.
- Added a stable `InterchangeError` error type.
- Added a PRISM-to-openLCA JSON-LD ZIP exporter baseline.
- Added an openLCA JSON-LD ZIP-to-PRISM preview importer baseline.
- Added deterministic ZIP generation and openLCA schema version 2 manifest generation.
- Added complete-reference checks for Models, Processes, Flows, Flow Properties, and Unit Groups during export.
- Added ZIP path traversal, symbolic-link, entry-count, compressed-size, and expanded-size checks during import.
- Added exact UUID and normalized-name conflict proposals for import previews.
- Added a versioned PRISM extension under openLCA `otherProperties` for lossless round trips when a package has not been edited.
- Added focused conversion tests.
- Verified that repeated export produces byte-identical output.
- Verified a synthetic Model round trip with no payload loss.
- Verified all 77 records in the current PRISM seed snapshot:
  - 10 Models
  - 18 Processes
  - 31 Flows
  - 4 Flow Properties
  - 4 Unit Groups
  - 10 Sources
- Verified that the resulting real-data ZIP can be read by the official `olca-schema` Python reader.

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
- Verify the generated real-data package by importing it into openLCA and inspecting the Product System graph.
- Add graph tests with multiple Processes and Process Links.
- Add tests for edited openLCA packages, missing references, duplicate IDs, unsupported entity types, and malformed entity documents.
- Decide whether to keep the core converter in one module or split it into archive, import, export, and mapping modules before the HTTP batch.
- Document every field that cannot be represented directly in both systems.

## Goal

Allow a PRISM user to import and export an industry-relevant LCA exchange package. The first supported format is the openLCA schema version 2 JSON-LD ZIP format.

The first release supports two operations:

1. Import an openLCA JSON-LD ZIP and return normalized PRISM datasets for review.
2. Export a PRISM Model and its referenced datasets as an openLCA JSON-LD ZIP.

Additional formats such as ILCD/eILCD and EcoSpold 2 can be added after the openLCA workflow is complete and validated. They are outside the first release.

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
- Supabase authentication and database access happen in the browser
- One `datasets` table stores seven dataset types:
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
  - file picker and browser download
  - export selection and referenced-dataset collection
  - import preview and conflict decisions
  - Supabase writes using the signed-in user's session

LCA engine
  - openLCA package detection and safety checks
  - PRISM/openLCA field mapping
  - reference and graph validation
  - deterministic ZIP generation
  - temporary-file management

Supabase
  - user authentication
  - permanent PRISM dataset storage
  - atomic confirmed import
```

The engine does not permanently store uploaded or generated packages. Supabase remains the only permanent user-data store.

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

An exported ZIP contains a root manifest and one JSON document per dataset:

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

## Export workflow

```text
User selects a PRISM Model
  → PRISM loads the Model and its complete referenced dataset closure
  → PRISM sends the bundle to the engine
  → engine validates types, IDs, and references
  → engine maps the records to openLCA entities
  → engine creates a deterministic JSON-LD ZIP
  → browser downloads the ZIP
```

### Export endpoint

```http
POST /api/interchange/export/openlca
Authorization: Bearer <Supabase access token>
Content-Type: application/json
```

Request:

```json
{
  "models": [],
  "processes": [],
  "flows": [],
  "flow_properties": [],
  "unit_groups": [],
  "sources": [],
  "contacts": []
}
```

The request must contain the full closure required by the selected Model. A missing required Process, Flow, Flow Property, or Unit Group returns a structured `422` error instead of a partial package.

Successful response:

```http
HTTP/1.1 200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="prism-openlca.zip"
```

### Model and graph mapping

- PRISM Model becomes openLCA `ProductSystem`.
- `processInstances` become `ProductSystem.processes` references.
- The selected reference Process becomes `refProcess`.
- Its quantitative-reference exchange becomes `refExchange`.
- Model connections become `ProcessLink` entries.
- The exporter infers a connection's Flow and consumer exchange from the provider's quantitative-reference output and the consumer's matching input.
- The reference Process multiplication factor contributes to `targetAmount`.

openLCA does not directly store a multiplication factor for every occurrence in a Product System. PRISM also allows graph information that may not have a direct openLCA field. To preserve exact round trips, exported root entities contain:

```text
otherProperties.prismInterchange
```

The extension contains the original PRISM payload and a hash of the standard openLCA fields. On import:

- If the standard fields are unchanged, the importer restores the exact PRISM payload.
- If openLCA changed the entity, the hash differs and the importer rebuilds the PRISM payload from the edited standard fields.
- A stale extension produces a warning and never overrides edited openLCA content.

## Import workflow

```text
User selects an openLCA JSON-LD ZIP
  → browser uploads it to the engine
  → engine checks the ZIP and manifest
  → engine reads supported openLCA entities
  → engine maps them to normalized PRISM datasets
  → engine validates references and proposes conflict decisions
  → PRISM shows the preview
  → user confirms create/update/skip decisions
  → PRISM writes the approved batch through a Supabase RPC
```

Import preview and database persistence remain separate. The preview endpoint never writes to Supabase.

### Import preview endpoint

```http
POST /api/interchange/import/openlca/preview
Authorization: Bearer <Supabase access token>
Content-Type: multipart/form-data

file=<openLCA JSON-LD ZIP>
catalog=<optional compact existing-dataset catalog>
```

Suggested response:

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
  "datasets": [
    {
      "temporary_id": "import:process:<source-id>",
      "source_id": "<openlca-id>",
      "id": "<proposed-prism-uuid>",
      "type": "process",
      "name": "Steel production",
      "description": "",
      "payload": {},
      "decision": "create"
    }
  ],
  "matches": [],
  "warnings": [],
  "errors": []
}
```

Initial conflict rules:

- Same UUID: propose `update` with confidence `1.0`.
- Same normalized type and name under a different UUID: propose `review` with confidence `0.9`.
- No match: propose `create`.
- The user can change any proposal to create, update, reuse, or skip in the PRISM UI.

Unsupported openLCA entities such as Impact Methods, Currencies, Parameters, Results, and DQ Systems are ignored with warnings in the first release. Supported entities that reference missing datasets remain visible in the preview with unresolved-reference warnings.

## Import confirmation

PRISM writes the reviewed rows using the authenticated user's Supabase session and Row Level Security.

A Supabase RPC/database function must apply the entire reviewed import in one transaction:

1. Validate dataset types and UUIDs.
2. Validate internal references after applying create/reuse/update mappings.
3. Insert or update the full batch.
4. Return final dataset IDs and decisions.
5. Roll back the entire batch on any constraint or reference failure.

The engine never receives a Supabase service-role key from the browser.

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
├── openlca_export.py
├── openlca_import.py
├── references.py
└── validation.py
```

HTTP routes in `lca_server.py` remain thin. They authenticate, enforce limits, parse requests, call `lca_core.interchange`, and serialize the response. Field mapping and archive rules do not belong in the HTTP adapter.

## Authentication and browser access

Conversion endpoints must require a valid Supabase user token before production deployment.

Required controls:

1. Accept `Authorization: Bearer <Supabase access token>`.
2. Verify signature, issuer, audience, expiration, subject, and authenticated role.
3. Cache the Supabase JWKS response while respecting signing-key rotation.
4. Add `https://catiehe.github.io` to the exact CORS allowlist.
5. Keep explicit local development origins.
6. Allow `Authorization` and `Content-Type` request headers.
7. Expose `Content-Disposition` to browser JavaScript.
8. Do not log tokens or uploaded dataset content.

The current engine REST endpoints remain unchanged. Authentication is applied to the new conversion routes during batch 4.

## Archive and resource safety

Initial configurable defaults:

- 25 MB compressed upload
- 250 MB total expanded content
- 5,000 archive entries
- 120-second conversion timeout
- One or two active conversion jobs per user

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
- `401`: missing or invalid Supabase token
- `413`: compressed or expanded package exceeds limits
- `422`: valid request whose data or references cannot be converted
- `429`: rate or per-user concurrency limit
- `500`: unexpected conversion failure
- `504`: conversion timeout

## Delivery batches

### Batch 1: contract and fixtures

Status: complete.

- Define the openLCA schema version and ZIP layout.
- Define the seven dataset mappings.
- Define graph, reference, error, and conflict contracts.
- Capture representative PRISM data from the current seed snapshot.
- Record round-trip limitations and extension behavior.

### Batch 2: export core

Status: in progress with a working baseline.

- Validate PRISM bundle shape and required references.
- Convert all seven PRISM dataset types.
- Generate Unit IDs deterministically from Unit Group UUID and internal ID.
- Generate Product Systems, Process Links, quantitative references, and units.
- Generate deterministic ZIP output.
- Validate with the official openLCA schema reader.
- Import a generated package into openLCA desktop and inspect the graph.

### Batch 3: import preview core

Status: started; engine-generated round trips work.

- Validate archive structure and manifest.
- Read all seven supported openLCA entity types.
- Normalize external openLCA entities into PRISM payloads.
- Restore exact PRISM payloads only when the extension hash is current.
- Return counts, rows, match proposals, and warnings.
- Test packages created and edited by openLCA desktop.

### Batch 4: engine HTTP integration

Status: not started.

- Add Supabase JWT verification.
- Add the PRISM production CORS origin and required headers.
- Add multipart upload support.
- Add the import preview and export routes.
- Add upload streaming limits, concurrency limits, timeout, and cleanup.
- Add HTTP and security tests.

### Batch 5: PRISM UI and persistence

Status: not started.

- Add import file selection and upload progress.
- Add preview counts, warnings, errors, and record details.
- Add create/update/reuse/skip decisions.
- Add Model export selection and complete-closure collection.
- Add browser download handling.
- Add the atomic Supabase batch-import RPC.
- Add an end-to-end import/export report.

## Required tests

### Export tests

- Every supported PRISM type is written to the correct openLCA folder.
- Every JSON filename matches its `@id`.
- Process exchanges reference packaged Flows, Flow Properties, and Units.
- Product System reference Process and exchange resolve.
- Process Links use the expected provider, consumer, Flow, and exchange.
- UUID and Unit ID generation is deterministic.
- Repeated export is byte-identical.
- The official openLCA reader accepts the package.

### Import tests

- A valid openLCA package produces the expected normalized counts.
- An engine-exported package round trips without PRISM payload loss.
- An openLCA-edited entity ignores a stale PRISM extension.
- Unsupported root types produce warnings.
- Missing references remain visible as warnings.
- Broken ZIP, malformed JSON, duplicate IDs, unsafe paths, symbolic links, and oversized packages are rejected.

### HTTP tests

- Valid Supabase JWT is accepted.
- Missing, expired, incorrectly issued, and incorrectly scoped JWTs are rejected.
- PRISM production CORS preflight succeeds.
- Unapproved origins receive no allow-origin header.
- Upload, timeout, and concurrency limits are enforced.
- `Content-Disposition` is exposed to browser JavaScript.
- Temporary files are deleted after successful and failed requests.

### End-to-end acceptance

1. Export a known multi-Process PRISM Model.
2. Import the ZIP into openLCA.
3. Confirm Processes, Flows, units, quantitative references, and Product System links are visible.
4. Export the package from openLCA.
5. Upload that package through the PRISM preview endpoint.
6. Review the reconstructed Model and references.
7. Confirm that no Supabase rows exist before approval.
8. Confirm the approved batch is committed atomically.
9. Export the imported Model again and compare its graph semantics.

## Completion criteria

The first release is complete when:

- A signed-in PRISM user can export a selected Model as an openLCA schema version 2 JSON-LD ZIP.
- openLCA can import the ZIP and display the Product System graph.
- A signed-in user can upload an openLCA ZIP and review normalized PRISM records before import.
- Confirmed records are written atomically to Supabase.
- Missing and ambiguous references are reported clearly.
- The engine retains no uploaded or generated files after the response completes.
- Authentication, CORS, archive safety, resource-limit, and cleanup tests pass.
- A PRISM → openLCA → PRISM round trip preserves graph semantics and supported dataset content.
