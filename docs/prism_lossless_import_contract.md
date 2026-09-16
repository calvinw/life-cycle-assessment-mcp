# PRISM Lossless Import Preview Contract

Prepared for `life-cycle-assessment-mcp` · 2026-09-16

Canonical product plan:
[`prism-dataset-manager/PLAN_LOSSLESS_IMPORT_UI.md`](https://github.com/catiehe/prism-dataset-manager/blob/main/PLAN_LOSSLESS_IMPORT_UI.md)

## Status and scope

Planning contract only. It has not been implemented.

This document defines the additive preview/provenance fields the LCA engine must
return so PRISM can preserve and display complete source uploads. It does not own
Supabase schema, Storage, UI sequencing, or product acceptance; those remain in
the canonical Dataset Manager plan.

Applies to:

- openLCA JSON-LD;
- TIDAS JSON;
- EcoSpold2 XML/ZIP;
- SimaPro CSV;
- ILCD/eILCD XML.

## Contract principles

1. Existing normalized `format`, `valid`, `summary`, `datasets`, `matches`,
   `warnings`, and `errors` fields remain backward compatible during rollout.
2. The engine is stateless and does not permanently store uploaded files.
3. The engine hashes and inventories the exact request body and, for archives,
   every safe entry.
4. The response identifies source locations; it does not need to echo the full
   upload as base64.
5. The browser uses these locators against its original `File` during preview.
6. Source locations and source content are never rewritten during PRISM UUID
   allocation.
7. Every normalized row is direct, derived, or synthetic and explains why.
8. Unsupported fields and entries are represented in coverage/warnings rather
   than silently discarded.

## Proposed response additions

```json
{
  "format": "tidas-json",
  "valid": true,
  "summary": {},
  "package": {
    "sha256": "lowercase hex",
    "byte_size": 12345,
    "media_type": "application/zip",
    "container": "zip",
    "manifest_locator": {
      "entry_path": "manifest.json",
      "selector": { "kind": "json-pointer", "value": "" }
    },
    "entries": [
      {
        "path": "processes/example.json",
        "byte_size": 4567,
        "sha256": "lowercase hex",
        "media_type": "application/json",
        "role": "dataset",
        "supported": true
      }
    ]
  },
  "datasets": [
    {
      "temporary_id": "import:process:...",
      "source_id": "...",
      "id": "...",
      "type": "process",
      "name": "Example",
      "description": "...",
      "payload": {},
      "decision": "create",
      "source": {
        "kind": "direct",
        "locators": [
          {
            "entry_path": "processes/example.json",
            "selector": {
              "kind": "json-pointer",
              "value": "/processDataSet"
            }
          }
        ],
        "mapping": {
          "status": "partial",
          "mapped": [
            {
              "source_path": "/processDataSet/processInformation/.../baseName",
              "target_path": "/processInformation/dataSetInformation/name/baseName",
              "mode": "exact"
            }
          ],
          "unmapped": [
            {
              "source_path": "/processDataSet/modellingAndValidation/validation/review",
              "reason": "normalized_schema_missing"
            }
          ],
          "derived": []
        }
      }
    }
  ],
  "warnings": [],
  "errors": []
}
```

Names may change during implementation, but the semantics and completeness
requirements in this document are fixed unless both repositories update their
contract documents together.

## Package contract

### Hashes

- `package.sha256` hashes the exact HTTP request body.
- `package.byte_size` is the exact request-body length.
- Each archive entry hash is calculated from its uncompressed bytes.
- Hash encoding is lowercase hexadecimal SHA-256.
- Hashing must stream where possible and obey existing compressed/expanded size
  and entry-count limits.

### Entry inventory

Inventory every safe entry, including:

- manifests;
- supported datasets;
- unsupported dataset types;
- metadata and master-data entries;
- attachments and binary files;
- otherwise ignored files.

Directories may be omitted. Unsafe paths and symlinks remain hard errors under
the existing archive safety rules and must never enter the inventory.

Entry roles:

- `manifest`
- `dataset`
- `master_data`
- `attachment`
- `metadata`
- `unsupported`
- `unknown`

`supported` means the entry participates in normalization, not that all its
fields are mapped.

For a raw XML or CSV upload, expose one logical entry such as `upload` while
retaining `container: "raw"`.

## Source locators

Common locator shape:

```json
{
  "entry_path": "datasets/example.spold",
  "selector": {
    "kind": "xml-identity",
    "value": {
      "element": "activityDataset",
      "activity_id": "..."
    }
  },
  "label": "Activity Example"
}
```

Supported selector kinds:

- `json-pointer` — RFC 6901 pointer within a JSON entry;
- `xml-identity` — stable element name plus UUID/identity attributes;
- `xml-path` — namespace-aware path when there is no stable identity;
- `csv-lines` — inclusive physical line range plus optional section/record
  identity;
- `archive-entry` — whole entry;
- `raw-file` — whole non-archive upload.

Line ranges refer to decoded source lines but must also carry the detected
encoding. They are navigation aids; exact fidelity always comes from artifact
bytes and hashes.

## Provenance kinds

### `direct`

The normalized row corresponds to a source dataset record, such as one TIDAS
Process JSON object or one EcoSpold2 Activity.

### `derived`

The normalized row is built from source elements that are not a standalone
dataset in that format, such as a Flow Property reconstructed from an exchange
unit. `locators` must include every material source used for derivation.

### `synthetic`

The normalized row has no direct format equivalent and was created for PRISM,
such as a Model inferred from SimaPro product names or EcoSpold2 activity links.
The response must include a machine-readable `reason` and all supporting
locators.

No row may omit provenance. If a locator cannot be produced, return an explicit
contract error during development rather than silently shipping an untraceable
row.

## Mapping coverage

Mapping coverage describes source-to-normalized conversion, not whether a field
currently has a specialized UI.

Allowed row-level status:

- `complete` — every meaningful source leaf is mapped exactly;
- `partial` — at least one source leaf is unmapped or flattened;
- `derived` — the normalized row is reconstructed from lower-level source data;
- `synthetic` — the row has no direct source record.

Mapping modes:

- `exact` — value and semantics preserved;
- `flattened` — structure/metadata reduced, e.g. classification objects to text;
- `converted` — representation changes without intended semantic loss;
- `inferred` — value inferred rather than explicitly present;
- `defaulted` — PRISM default supplied;
- `derived` — calculated from multiple source fields;
- `omitted` — not present in normalized payload.

Every unmapped item contains:

- a source path;
- a reason code;
- optional human message;
- a resolvable locator or parent locator.

Suggested reason codes:

- `normalized_schema_missing`
- `unsupported_dataset_type`
- `unsupported_section`
- `unsupported_field`
- `flattened_reference_metadata`
- `flattened_classification`
- `computed_output_not_imported`
- `format_semantics_not_representable`
- `unsafe_or_invalid_source`

Coverage generation should inventory scalar leaves plus meaningful empty
containers. Empty review/parameter sections should not generate noise, but a
non-empty unsupported section must always appear.

## Warning and error contract

Existing shape remains:

```json
{
  "code": "UNSUPPORTED_ECOSPOLD2_FIELDS",
  "message": "...",
  "details": {}
}
```

Add source navigation inside `details` where relevant:

```json
{
  "entry_path": "datasets/example.spold",
  "selector": {
    "kind": "xml-identity",
    "value": { "element": "uncertainty", "parent_exchange_id": "..." }
  },
  "source_paths": ["..."]
}
```

Warnings summarize coverage problems for humans. They do not replace the
machine-readable mapping report.

## Format requirements

### openLCA JSON-LD

- Inventory every ZIP entry and every official root-entity folder encountered.
- Direct rows use entry path plus root JSON pointer.
- Report unsupported root entities without discarding their entries from the
  inventory.
- Inventory unmapped fields of the seven supported roots, including arbitrary
  `otherProperties` except the engine's recognized PRISM extension.
- If the PRISM extension restores a payload, coverage still compares the full
  current openLCA entity; source visibility never depends on extension validity.

### TIDAS JSON

- Inventory manifest entries and all root-level dataset files.
- Locate the expected dataset root even when extra siblings such as `json_tg`
  exist; inventory those siblings as well.
- Treat namespace/schema attributes as source metadata, not disposable parser
  noise.
- Mark flattened classification/reference metadata explicitly.
- Report validation, review, compliance, model-connection, and other unmapped
  source paths individually or by a resolvable subtree prefix.

### EcoSpold2

- A direct Process locator identifies its Activity UUID.
- Flow provenance lists every exchange occurrence used for that reconstructed
  Flow.
- Unit Group and Flow Property provenance points to unit identifiers/names on
  exchanges and is `derived`.
- Model provenance lists activity-link elements and is `synthetic`.
- Current unsupported-field detection gains exact locators.
- `childActivityDataset`, parameters, impact indicators, reviews, uncertainty,
  allocation, pedigree, properties, transfer coefficients, classifications,
  representativeness, master data, and other unnormalized content remain
  inventoried/browsable.

### SimaPro CSV

- Preserve detected encoding, delimiter, decimal separator, and header lines in
  package metadata/locators.
- Process and exchange locators include physical line ranges.
- Unknown process metadata fields receive warning plus locator.
- Non-empty unsupported sections receive unmapped coverage with line ranges.
- Methods and Product Stages remain unsupported for normalized import initially,
  but the engine must identify the file type and provide enough package metadata
  for the Dataset Manager to display the original CSV before explaining why
  confirmation is unavailable.
- Reconstructed Model is `synthetic`; reconstructed reference data is `derived`.

### ILCD/eILCD

- Direct datasets use entry path plus dataset UUID/root element.
- Preserve and locate namespace/schema metadata, full references, mathematical
  relations, reviews, compliance, LCIA structures, and life-cycle-model details.
- Apply equivalent coverage semantics to TIDAS mappings so the two converters do
  not drift silently.

## Compatibility and rollout

1. Add optional package/source fields and tests without removing old fields.
2. Deploy the engine first.
3. Dataset Manager feature-detects the new contract.
4. During development, old responses may still preview, but confirmation into
   the new lossless workflow must be disabled with a clear message when package
   provenance is missing.
5. Once both deployments are stable, increment a contract version and make
   provenance mandatory for confirmation.

Recommended top-level field:

```json
{ "contract_version": 2 }
```

The Dataset Manager must reject an unknown newer mandatory contract version
rather than guess at preservation semantics.

## Required engine tests

- Exact package and entry SHA-256 for every format.
- Complete entry inventory, including unsupported and binary entries.
- One direct locator per direct normalized row.
- Multi-locator provenance for derived rows.
- Explicit synthetic reason for inferred Models.
- Resolver tests that open fixture bytes and locate each reported selector.
- Coverage tests for known omitted fields in every format.
- No warning about omitted source data without a locator.
- No normalized row without provenance.
- Existing normalized import/export tests remain green.
- Archive traversal, symlink, bomb, size, and entry-count protections remain
  unchanged or stronger.

## Engine definition of done

The engine portion is complete when, for every accepted preview:

- exact request and entry hashes are returned;
- all safe package entries are inventoried;
- every normalized row is traceable to direct/derived/synthetic source evidence;
- every meaningful source field has a mapping classification;
- unsupported data has a locator and is never warning-only;
- the response remains within operational limits without embedding the entire
  upload;
- Dataset Manager can resolve every locator against the original browser File
  and the persisted Storage artifact.
