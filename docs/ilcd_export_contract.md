# ILCD/eILCD export contract

This document defines the supported PRISM-to-ILCD/eILCD export subset. It is
the inverse of `docs/ilcd_interchange_contract.md` and shares the normalized
seven-array PRISM bundle used by the openLCA JSON-LD exporter.

## Package layout

The deterministic ZIP contains one XML document per exported dataset:

| PRISM type | ILCD member |
| --- | --- |
| `model` | `ILCD/lifecyclemodels/<uuid>.xml` |
| `process` | `ILCD/processes/<uuid>.xml` |
| `flow` | `ILCD/flows/<uuid>.xml` |
| `flow_property` | `ILCD/flowproperties/<uuid>.xml` |
| `unit_group` | `ILCD/unitgroups/<uuid>.xml` |
| `source` | `ILCD/sources/<uuid>.xml` |
| `contact` | `ILCD/contacts/<uuid>.xml` |

Dataset UUIDs are preserved. XML uses the ILCD 1.1 dataset namespaces already
accepted by the importer. Identical normalized input produces identical ZIP
bytes, including member order and timestamps.

## Supported mapping

- Model `processInstances` become ILCD lifecycle-model `processInstance`
  elements.
- Flat PRISM `connections` become nested `outputExchange/downstreamProcess`
  links beneath their upstream Process instance.
- Process quantitative references, exchange internal IDs, directions, mean and
  resulting amounts are preserved.
- Flow quantitative references and Flow Property factors are preserved.
- Flow Properties retain their Unit Group references.
- Unit names, conversion factors, and reference-unit internal IDs are
  preserved.
- Dataset names, descriptions, classifications, versions, timestamps,
  locations, reference years, citations, and supported Contact fields are
  emitted when present.
- Cross-dataset references include their UUID, ILCD reference type, version,
  and short description.

## Validation boundary

Export fails atomically before serialization for duplicate dataset UUIDs,
array/type mismatches, missing required dependencies, duplicate internal IDs,
unresolved quantitative references, or Model connections whose endpoints are
not present. Optional Source and Contact references may be absent.

When a `model_id` is supplied, only that Model and its transitive dependency
closure are exported. Unrelated workspace records are excluded and do not need
to be serialized.

## Round-trip promise

`export_ilcd()` followed by `preview_ilcd()` preserves the supported semantic
fields: identities and types, quantitative references, Process exchanges,
Model instances and graph connections, Flow Property/Unit Group references,
and supported Source/Contact metadata.

Whole-payload equality is not promised. The current ILCD path does not add a
private PRISM extension, and unsupported PRISM-only fields may therefore be
defaulted or omitted. XML byte equality after openLCA Desktop rewrites a
package is also not expected.

## Known limitations before Desktop acceptance

- The generated lifecycle-model XML passes the official eILCD 2.1.1 lifecycle
  model XSD. The other six dataset types pass the engine round-trip suite but
  still require validation against their official ILCD 1.1 XSDs.
- Both package variants still require acceptance testing against openLCA
  Desktop.
- Location master-data tables and classification master-data files are not yet
  generated.
- LCIA methods, calculation results, mathematical relations, uncertainty,
  allocation, and external binary sources are outside the first release.
- Connection Flow metadata is reconstructed from Process exchanges by target
  applications; the PRISM graph itself preserves only Process instance edges.
