# PRISM dual-format export implementation plan

Extends the existing openLCA JSON-LD and ILCD/eILCD import work with one
user-facing **Export** feature. The feature ships both output formats together:

- openLCA schema version 2 JSON-LD ZIP
- ILCD/eILCD XML ZIP

Last updated: 2026-09-15

## Goal

A user selects a PRISM Model and downloads a self-contained ZIP in either
supported format. The package contains the selected Model and every transitive
Process, Flow, Flow Property, Unit Group, Source, and Contact needed by that
Model. It can be opened by openLCA Desktop and can be imported back through the
engine without silently changing supported graph or calculation semantics.

Both formats are delivered as one feature, one endpoint, and one frontend flow.
Internally they remain separate serializers behind a shared validated bundle
contract.

## Current baseline

| Area | Status |
| --- | --- |
| openLCA core serializer | Implemented as `export_openlca()` |
| openLCA deterministic ZIP test | Implemented |
| openLCA exact extension-assisted round trip | Implemented |
| ILCD importer | Implemented and tested with a real openLCA Desktop export |
| ILCD core serializer | Not implemented |
| Export HTTP endpoint | Not implemented |
| PRISM Export UI/download | Not implemented |
| Desktop acceptance tests | Not completed for generated exports |

The openLCA baseline is useful but is not yet a complete user feature. It has no
HTTP delivery path or frontend download action, and it has not yet passed the
acceptance matrix in this plan.

## Scope and non-goals

### Included

- Export one selected Model and its complete dependency closure.
- Export a caller-supplied complete workspace bundle when no Model filtering is
  requested by the client.
- Generate deterministic ZIPs for identical input.
- Preserve stable PRISM UUIDs wherever the target format supports UUIDs.
- Return structured validation errors before generating a partial package.
- Support all seven PRISM dataset types in both serializers.
- Round-trip generated packages through the existing importers.
- Verify both generated formats in openLCA Desktop.

### Not included in the first release

- EcoSpold, SimaPro CSV, or another interchange format.
- Exporting calculation results or LCIA methods.
- Database persistence, merge/conflict handling, or asynchronous export jobs.
- Perfect preservation of target-format fields that PRISM cannot represent.
- Bit-for-bit equality after a Desktop application rewrites a package.

## Public API contract

Use one format-neutral route:

```http
POST /api/interchange/export
Content-Type: application/json
Accept: application/zip
```

Request:

```json
{
  "format": "openlca-json-ld",
  "model_id": "<optional selected PRISM model UUID>",
  "datasets": {
    "models": [],
    "processes": [],
    "flows": [],
    "flow_properties": [],
    "unit_groups": [],
    "sources": [],
    "contacts": []
  }
}
```

`format` is either `openlca-json-ld` or `ilcd-xml`. When `model_id` is present,
the engine computes the dependency closure and excludes unrelated workspace
records. When absent, it validates and exports the supplied bundle as-is.

Success response:

```http
200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="<safe-name>.<format>.zip"
```

Failures use the existing interchange error envelope:

```json
{
  "error": {
    "code": "UNRESOLVED_DATASET_REFERENCE",
    "message": "The selected Model references a Process outside the export bundle.",
    "details": {}
  }
}
```

Initial response generation may stay in memory under the existing package-size
limits. Streaming plus post-response temporary-file cleanup is only required if
real packages show that in-memory generation is insufficient.

## Shared export pipeline

```text
PRISM workspace + optional model_id
  -> normalize the seven dataset arrays
  -> reject duplicate IDs and type/array mismatches
  -> compute selected Model dependency closure
  -> validate all required references and quantitative references
  -> dispatch to the selected format serializer
  -> validate the generated package structurally
  -> return ZIP download
```

Shared code owns bundle normalization, dependency traversal, stable errors,
safe filenames, deterministic archive metadata, and output-size enforcement.
Format modules only own field mapping and serialization.

## Format-specific contracts

### openLCA JSON-LD

Keep the existing mapping in `docs/openlca_interchange_contract.md` and the
existing `export_openlca()` public function. Before exposing it over HTTP:

- run it through the shared bundle validator;
- cover multi-Process Product Systems and Process Links;
- test all seven dataset types together;
- verify that invalid or incomplete bundles fail atomically;
- open a generated package in openLCA Desktop and re-export it;
- retain `otherProperties.prismInterchange` for exact PRISM round trips when
  standard openLCA fields remain unchanged.

### ILCD/eILCD

Add `lca_core/interchange/ilcd_export.py` with
`export_ilcd(bundle: dict) -> bytes`. It is the inverse of the supported subset
in `lca_core/interchange/ilcd.py`:

| PRISM type | ILCD ZIP member |
| --- | --- |
| `model` | `ILCD/lifecyclemodels/<uuid>.xml` |
| `process` | `ILCD/processes/<uuid>.xml` |
| `flow` | `ILCD/flows/<uuid>.xml` |
| `flow_property` | `ILCD/flowproperties/<uuid>.xml` |
| `unit_group` | `ILCD/unitgroups/<uuid>.xml` |
| `source` | `ILCD/sources/<uuid>.xml` |
| `contact` | `ILCD/contacts/<uuid>.xml` |

Implementation order within the serializer:

1. Unit Groups and Flow Properties.
2. Flows and their reference Flow Properties.
3. Sources and Contacts.
4. Processes, exchanges, directions, amounts, location, and quantitative
   reference.
5. Models, Process instances, multiplication factors, and nested ILCD lifecycle
   connections.
6. Namespaces, administrative information, versions, and deterministic XML/ZIP
   output.

Use official ILCD namespaces and XML escaping. Reject values that cannot be
represented safely. Do not insert an unverified private XML extension merely to
make tests pass; the first ILCD round-trip target is semantic equality for the
supported fields. Exact PRISM payload restoration can be added only after a
namespaced extension is shown to remain XSD-valid and interoperable.

## Round-trip definition

Round-trip tests compare normalized semantics, not ZIP bytes between different
applications.

For openLCA JSON-LD, an unchanged engine-generated package must restore exact
supported PRISM payloads through the existing hash-guarded extension. A package
edited or rewritten by openLCA Desktop must preserve standard supported fields
and graph semantics even if extension data or JSON ordering changes.

For ILCD, export followed by the existing ILCD importer must preserve:

- dataset IDs, types, names, and descriptions;
- quantitative references;
- Process exchange flow, direction, and amount;
- Model Process instances, reference Process, multiplication factors, and
  connections;
- Flow Property to Unit Group references;
- supported Source and Contact fields.

Known lossy or defaulted metadata must be listed as warnings or documented in a
field-loss table. It must not be hidden by asserting whole-payload equality.

## Delivery steps

Each step is independently reviewable and testable.

### Step E0 - Freeze the export contract and fixtures

Status: complete for the engine fixture and contract; frontend request review remains.

- Add a representative multi-Process PRISM fixture using all seven dataset
  types and at least two Model connections.
- Record the expected dependency closure for one selected Model.
- Add `docs/ilcd_export_contract.md` with required namespaces, field mappings,
  defaults, and known losses.
- Freeze the request, binary response, filename, and error contracts above.

Done when the same fixture and assertions can drive both serializers without
format-specific changes to the input bundle.

### Step E1 - Shared validation and selection

Status: complete.

- Extract bundle validation from format-specific code where practical.
- Validate array/type consistency, UUIDs, duplicate IDs, internal IDs,
  quantitative references, and required cross-dataset references.
- Implement deterministic dependency-closure traversal from `model_id`.
- Define stable errors for an unknown Model, duplicate record, missing
  dependency, unsupported format, and oversized output.

Done when a valid fixture produces the expected closure and every incomplete
fixture fails before either serializer runs.

### Step E2 - Complete and harden openLCA export

Status: complete for automated engine tests; Desktop acceptance remains in E6.

- Route the current `export_openlca()` through E1 validation.
- Add multi-Process graph, all-seven-types, invalid-bundle, and deterministic
  output tests.
- Confirm export/import exactness for unchanged engine packages.
- Confirm stale extensions never overwrite standard fields after edits.

Done when the expanded automated suite passes without relying only on the
current one-Process fixture.

### Step E3 - Implement ILCD export bottom-up

Status: complete for the supported semantic subset. The lifecycle-model output
passes the official eILCD 2.1.1 XSD; the six ILCD 1.1 dataset schemas and
Desktop acceptance remain in E6.

- Implement the seven XML serializers in the order listed above.
- Reconstruct ILCD lifecycle-model nested connections from PRISM's flat Model
  connections.
- Emit a self-contained `ILCD/` package with deterministic filenames and ZIP
  metadata.
- Add malformed input, escaping, namespaces, reference, and round-trip tests.

Done when the shared fixture exports to ILCD and `preview_ilcd()` reconstructs
the supported semantic fields and complete Model graph.

### Step E4 - Add the unified HTTP download route

Status: complete locally.

- Add `POST /api/interchange/export` without removing the existing import route.
- Dispatch by the explicit `format` request field; do not infer an export format.
- Return binary ZIP bytes with safe `Content-Disposition` and no dataset content
  in logs.
- Enforce JSON request and generated-output limits.
- Add route tests for both formats, headers, malformed JSON, unknown formats,
  structured errors, and non-leaking unexpected failures.

Done when both response bodies can be opened as ZIP files and imported through
`preview_interchange()`.

### Step E5 - Build one PRISM Export UI

Status: not started; belongs in the PRISM repository.

- Add one Export action near the current import/workspace controls.
- Let the user choose a Model and either `openLCA JSON-LD` or `ILCD/eILCD`.
- Resolve the selected Model's workspace records or send the complete workspace
  with `model_id` for server-side closure.
- Download the binary response using the server-provided filename.
- Render the existing structured error message when generation fails.
- Keep export stateless; do not write to Supabase.

Done when the same Model can be downloaded in both formats from one UI without
refreshing or rebuilding the workspace.

### Step E6 - Desktop and end-to-end acceptance

Status: in progress. ILCD/eILCD passed manual openLCA 2.6.2 import and
Desktop re-export acceptance on 2026-09-15: all seven supported dataset types,
Process exchanges, and the two-Process graph connection survived the round
trip with no warnings or errors. openLCA normalized Process-instance
`multiplicationFactor` values to `0.0`, as documented in the ILCD export
contract. JSON-LD Desktop acceptance and the deployed frontend pass remain.

For each format:

1. Export the shared multi-Process fixture through the real HTTP route.
2. Import the ZIP into openLCA Desktop without manually editing the package.
3. Inspect dataset counts, quantitative references, exchanges, units, and the
   Product System/lifecycle-model graph.
4. Re-export from Desktop and feed that result to the engine importer.
5. Compare supported semantics and record every intentional loss or Desktop
   normalization.
6. Repeat once through the production frontend and deployed engine.

Done when both formats pass the matrix and any accepted differences are written
into their interchange contracts.

## Test matrix

| Test | openLCA | ILCD |
| --- | --- | --- |
| Deterministic engine ZIP | Required | Required |
| All seven dataset types | Required | Required |
| Multi-Process graph | Required | Required |
| Missing dependency fails atomically | Required | Required |
| Core export -> core import | Exact supported payload | Semantic equality |
| Generated ZIP opens in openLCA Desktop | Required | Required |
| Desktop re-export -> engine import | Required | Required |
| HTTP headers and download filename | Required | Required |
| Frontend download | Required | Required |

## Main risks and decisions

- **ILCD graph direction:** the importer flattens nested downstream links;
  export must implement and test the precise inverse rather than guessing from
  array order.
- **Loss expectations:** openLCA currently has a guarded PRISM extension; ILCD
  does not. The two formats therefore have different round-trip equality rules.
- **Incomplete frontend state:** exporting only a Model row is insufficient.
  The shared closure validator must identify missing dependencies clearly.
- **Desktop compatibility:** an engine round trip alone does not prove a valid
  industry-facing export. Desktop acceptance is a release gate for both formats.
- **Memory:** keep the first endpoint synchronous and in-memory only while real
  output sizes remain within the configured limits; otherwise move ZIP creation
  to a temporary file with cleanup after response completion.

## Estimate

With the existing openLCA exporter and ILCD importer as reference
implementations, estimated active work is **2-4 engineering days**:

- E0-E1: 0.5-1 day
- E2: 0.5 day
- E3: 1-2 days
- E4: 0.5 day
- E5: 0.5-1 day in the PRISM repository
- E6: 0.5 day when openLCA Desktop and deployment access are available

Desktop findings may add another iteration. The feature is not complete merely
because both in-process round-trip tests pass.

## Completion criteria

The dual-format Export feature is complete when:

- one PRISM UI exports the selected Model as either openLCA JSON-LD or ILCD;
- both packages contain the complete required dependency closure;
- both serializers reject invalid bundles atomically with stable errors;
- both formats pass their defined engine round-trip tests;
- both generated packages open successfully in openLCA Desktop;
- Desktop-rewritten packages import back with supported graph and calculation
  semantics intact;
- generated files are not retained by the engine after delivery.
