# TIDAS JSON schema alignment: what went wrong and what's true

Written after building `lca_core/interchange/tidas_export.py` (PRISM → TIDAS
JSON export) the slow way: five rounds of upload-to-Tiangong-and-see-what-fails
before switching to reading `tiangong-lca/tidas-spec`'s actual JSON Schema
files directly. This doc exists so nobody (human or model) repeats that.

## The mistake

The first version of `tidas_export.py` was written by porting field
assumptions from `ilcd_export.py` (the existing ILCD XML exporter), on the
assumption that Tiangong's JSON Schema was roughly as strict as bare ILCD.
It wasn't. That produced a validation report with 86 schema errors, and each
subsequent round of "fix what the report says, re-upload" peeled off maybe
half the remaining errors — 86 → 41 → 24 → 20 → 4 → 0, five rounds total.
Several of those rounds also introduced *new* wrong guesses (e.g. flipping
numeric field types from string to number and back) that a direct schema
read would have gotten right immediately.

**The actual fix for what should have happened:** before writing any of
this, fetch and read `tiangong-lca/tidas-spec`'s schema files directly:

```text
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_data_types.json     # shared $defs: GlobalReferenceType, FTMultiLang, Version, LevelType, ...
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_processes.json      # Process: review, compliance, classification
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_flows.json
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_flowproperties.json
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_unitgroups.json
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_lifecyclemodels.json
https://raw.githubusercontent.com/tiangong-lca/tidas-spec/main/assets/tidas/schemas/tidas_*_category.json     # per-type classification code tables
```

These are small, plain JSON Schema files (Draft 7-ish, `$ref`/`$defs`/`anyOf`/`oneOf`/`allOf`).
Fetching and reading `tidas_processes.json` end to end takes a few minutes and
would have surfaced nearly everything below in one pass, instead of across
five rounds of manual user testing (each round costs the user a real manual
upload/download cycle — don't treat it as a free retry loop).

## Concrete things the schema says that are easy to get wrong by guessing

- **Every dataset root** (`processDataSet`, `flowDataSet`, ...) requires
  `@xmlns`, `@xmlns:common`, `@xmlns:xsi`, `@xsi:schemaLocation`, `@version`,
  `@locations`. `flowDataSet` additionally requires `@xmlns:ecn`;
  `lifeCycleModelDataSet` additionally requires `@xmlns:acme`.
- **Numeric fields are NOT consistently typed.** `referenceToReferenceProcess`
  (Model) must be a JSON **integer**. `referenceToReferenceFlow` (Process),
  `referenceToReferenceFlowProperty` (Flow), `referenceToReferenceUnit`
  (UnitGroup), and exchange `meanAmount`/`resultingAmount` must all be JSON
  **strings** (`$defs/Real`, `$defs/Int5`, `$defs/Int6` all reject a number
  despite the "Int" name). `common:referenceYear` must be an **integer**
  (`$defs/Year`). There is no shortcut here other than checking each field's
  actual `type` in its `$defs` entry — don't assume a pattern from one field
  applies to a sibling field.
- **`common:class` (classification) has a different shape per dataset type**,
  because each type (`tidas_processes.json`, `tidas_flows.json`,
  `tidas_flowproperties.json`, `tidas_unitgroups.json`, `tidas_lifecyclemodels.json`)
  defines its own schema for it, not a shared template:
  - Process / Flow / Model: `common:class` is a JSON **array** (tuple form,
    up to 4 levels, each level requiring `@level`/`@classId`/`#text`).
  - FlowProperty / UnitGroup: `common:class` is a single **bare object**
    (same three fields, `@level` fixed at `"0"`).
  - `@classId` is checked against a real, type-specific category table
    (`tidas_flows_product_category.json` for Flow, `tidas_processes_category.json`
    for Process/Model, etc. — see `tidas_*_category.json` in the schemas
    folder). It is not free text; Tiangong runs a business-rule check
    (`product_category_unknown_class_id` / `product_category_text_mismatch`)
    that the `@classId` and `#text` are a real, matching pair from that
    type's table. `lca_core/interchange/tidas_export.py`'s `_CATEGORY_ROOT`
    hardcodes one confirmed-valid level-0 pair per type as an export
    placeholder — see that dict for current values. `source`/`contact`'s
    pairs are an *unverified guess* (never exercised by a real validation
    report because no test bundle has had source/contact data yet).
  - `common:classification` itself also carries an optional `@name`
    attribute (e.g. `"ISIC rev.4"`) — present in real Tiangong exports.
- **`modellingAndValidation.validation.review` differs by type.** Process's
  `review` schema has a `@type` enum (`"Not reviewed"`, `"Dependent internal
  review"`, ...) with a conditional `allOf/if/then/else`: `@type ==
  "Not reviewed"` needs nothing else, any other `@type` requires
  `common:scope` + `common:reviewDetails` +
  `common:referenceToNameOfReviewerAndInstitution` +
  `common:referenceToCompleteReviewReport`. **Model's `review` schema has no
  `@type` property at all** — it's `anyOf: [{required:
  [common:referenceToNameOfReviewerAndInstitution]}, array-of-same]`. Using
  Process's placeholder approach (`@type: "Not reviewed"`) for Model silently
  fails Model's `anyOf` because Model doesn't recognize `@type` as satisfying
  anything — this was one of the last bugs found, and it looked identical
  in the error report to the true root cause below, which delayed finding
  the real problem.
- **`modellingAndValidation.complianceDeclarations.compliance` requires 7
  fields**, not just `common:approvalOfOverallCompliance` +
  `common:referenceToComplianceSystem` (which is all a real ILCD sample
  shows): also `common:nomenclatureCompliance`, `common:methodologicalCompliance`,
  `common:reviewCompliance`, `common:documentationCompliance`,
  `common:qualityCompliance` — each independently one of `"Fully compliant"
  / "Not compliant" / "Not defined"`.
- **The actual root cause of a persistent `processInstance` `anyOf` failure**
  (present in every validation report from round 1 through round 5, ~20
  error-count's worth each time counted as a single anyOf failure) was that
  `connections.outputExchange` and its nested `downstreamProcess` both
  require `@version` (`tidas_lifecyclemodels.json`), which was never
  provided. Nothing in any error message named `@version` specifically —
  `anyOf` failures report only "no branch matched", not which field broke
  which branch. This was only found by reading the schema's `required` list
  directly.
- **`GlobalReferenceType`** (every `referenceToXxx` field) requires `@type`
  (enum: `source data set`, `process data set`, `flow data set`, `flow
  property data set`, `unit group data set`, `contact data set`, `LCIA
  method data set`, `other external file` — **`life cycle model data set` is
  NOT in this enum**, an open gap if a future reference ever needs to point
  at a Model), `@refObjectId` (lowercase-hex UUID, no version/variant
  constraint), `@version` (`NN.NN(.NNN)` pattern), `@uri`, and
  `common:shortDescription`.
- **A real Tiangong-exported JSON file is not guaranteed to have exactly one
  top-level key.** A real downloaded export had
  `{"json_tg": {}, "lifeCycleModelDataSet": {...}}` — an extra empty sibling
  key next to the actual dataset root. `tidas.py`'s importer must look up
  the expected root by name (already fixed — see `_read_json_member`), not
  assume the file has a single top-level key.

## Where this is implemented

- `lca_core/interchange/tidas_export.py` — the exporter these notes describe.
  `_CATEGORY_ROOT`, `_CLASS_IS_ARRAY`, `_placeholder_compliance`,
  `_placeholder_review` / `_placeholder_review_model` are the direct
  code-level answers to the points above; their docstrings cite this file.
- `lca_core/interchange/tidas.py` — the importer; `_read_json_member`'s
  docstring covers the `json_tg` sibling-key point.
- `tests/test_tidas_interchange.py` — regression tests pinning the
  non-obvious ones (forced arrays, `@version` on connections, UnitGroup's
  bare-object classification shape).
