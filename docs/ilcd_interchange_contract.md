# ILCD/eILCD interchange contract

Second import format for the PRISM data manager and the LCA engine, alongside
the openLCA JSON-LD contract (`docs/openlca_interchange_contract.md`). Read
that document first — this one only states what's different for ILCD.

The target is the ILCD (International Reference Life Cycle Data System) XML
ZIP layout, as produced by openLCA Desktop's "Export → ILCD" and by other LCA
tools that support ILCD/eILCD exchange. Export is not covered by this
contract; this is import-only, matching the openLCA JSON-LD release.

A real sample (`tests/fixtures/ilcd_plastic_broom.zip`, an openLCA-Desktop
export of a mock product system) grounds every rule below — this is real
data, not a synthetic fixture.

## Format detection

The same HTTP route (`POST /api/interchange/import/openlca`) accepts either
format. The engine sniffs the uploaded ZIP before choosing a reader:

```text
"olca-schema.json" at the ZIP root       → openLCA JSON-LD reader
a top-level "ILCD/" directory            → ILCD reader
neither                                  → UNSUPPORTED_PACKAGE_FORMAT (400)
```

Both readers return the exact same response shape. The route name stays
`.../openlca` for backward compatibility with the already-deployed frontend
call; it is not renamed even though it now accepts a second format.

## Dataset mapping

| PRISM type | ILCD folder | ILCD root element |
| --- | --- | --- |
| `model` | `ILCD/lifecyclemodels/` | `lifeCycleModelDataSet` |
| `process` | `ILCD/processes/` | `processDataSet` |
| `flow` | `ILCD/flows/` | `flowDataSet` |
| `flow_property` | `ILCD/flowproperties/` | `flowPropertyDataSet` |
| `unit_group` | `ILCD/unitgroups/` | `unitGroupDataSet` |
| `source` | `ILCD/sources/` | `sourceDataSet` |
| `contact` | `ILCD/contacts/` | `contactDataSet` |

`ILCD/lciamethods/` (Impact Methods) is read and ignored with a warning, the
same treatment openLCA JSON-LD gives Impact Methods/Currencies/Parameters/
Results/DQ Systems.

**Any of these folders may simply be absent from a real package.** The real
sample has no `flowproperties/`, `sources/`, or `contacts/` folders at all —
openLCA's ILCD exporter appears to omit a folder rather than emit an empty
one. The importer must not require any folder to exist.

## XML handling

- Parse with a namespace-aware XML reader. Every ILCD document declares
  several `xmlns:` prefixes (`common`, `f`, `p`/no-prefix for Process, `fp`,
  `u`, `model`, `s`, `c`); resolve elements by their namespace URI, not by
  prefix string, since a producer is free to use different prefixes for the
  same namespace.
- **Ignore unrecognized namespaces and attributes.** The real sample declares
  `xmlns:ns10="http://openlca.org/ilcd-extensions"` and uses it for
  `ns10:origin` and `ns10:linkedExchange`. This is an openLCA-specific
  extension, not part of the ILCD spec — a file from a different tool won't
  have it. Treat it as optional metadata, never a requirement.
- Multi-language text (`<f:baseName xml:lang="en">...</f:baseName>`) maps
  directly to PRISM's existing `[{"lang": "en", "text": "..."}]` shape — this
  is a structural copy, not a remapping, because PRISM's payload already uses
  ILCD-style field names.

## Reference resolution: required vs. warning-only

The openLCA JSON-LD contract treats a missing reference required by a Model,
Process, Flow, Flow Property, or Unit Group as a hard conversion error. **This
contract sets a narrower hard-error boundary for ILCD**, based on evidence
from the real sample rather than copying that rule directly:

- **Hard error** (`UNRESOLVED_DATASET_REFERENCE`, `422`): a Model's
  `referenceToReferenceProcess` or any `processInstance.referenceToProcess`
  cannot be resolved. A Model that can't resolve its own processes can't be
  viewed or calculated — there's no usable partial result.
- **Warning only**: a Flow's `referenceToReferenceFlowProperty`, or a
  Process exchange's flow reference, that cannot be resolved. The real
  sample's flow `03f77556-...` declares `referenceToReferenceFlowProperty=0`
  against an **empty** `<f:flowProperties/>` element — a legitimate
  openLCA-generated package with this exact gap. A Flow or Process with an
  unresolved secondary reference is still inspectable and worth returning;
  silently dropping it would be worse than showing it with a flagged gap.

Document any case this boundary gets wrong once Batch B's tests run against
real packages — this is a starting hypothesis grounded in one real file, not
a settled rule from multiple real-world samples.

## Model/graph mapping

ILCD represents process links **nested inside the upstream process
instance**, not as a flat list:

```xml
<model:processInstance dataSetInternalID="1" ...>
  <model:referenceToProcess refObjectId="..."/>
  <model:connections>
    <model:outputExchange flowUUID="...">
      <model:downstreamProcess id="0" flowUUID="..."/>
      <model:downstreamProcess id="2" flowUUID="..."/>
    </model:outputExchange>
  </model:connections>
</model:processInstance>
```

The importer flattens this into PRISM's `connections: [{fromInstanceId,
toInstanceId}]` shape: each `downstreamProcess/@id` under a given
`processInstance` becomes one connection from that instance to the
downstream `dataSetInternalID`. `ns10:linkedExchange`, when present, may help
disambiguate which exchange a connection targets, but the importer must not
require it — a spec-strict ILCD file won't have it.

## Safety limits

Same defaults as the openLCA JSON-LD contract: 25 MB compressed, 250 MB
expanded, 5,000 ZIP entries, with the same path-traversal/symlink checks
applied before any member is read. These checks are format-independent and
should be shared rather than duplicated between the two readers.
