# openLCA interchange contract

This document defines the first industry-facing import/export format for the
PRISM data manager and the LCA engine. The target is an openLCA schema version
2 JSON-LD ZIP package.

## Delivery batches

1. Contract and representative fixtures.
2. Transport-independent PRISM-to-openLCA export.
3. Transport-independent openLCA-to-PRISM import preview.
4. Authenticated HTTP upload/download routes and operational limits.
5. PRISM review UI and atomic Supabase persistence.

Each batch is independently reviewable and keeps conversion rules under
`lca_core/interchange` rather than in the HTTP adapter.

## Dataset mapping

| PRISM type | openLCA root type | ZIP folder |
| --- | --- | --- |
| `model` | `ProductSystem` | `product_systems/` |
| `process` | `Process` | `processes/` |
| `flow` | `Flow` | `flows/` |
| `flow_property` | `FlowProperty` | `flow_properties/` |
| `unit_group` | `UnitGroup` | `unit_groups/` |
| `source` | `Source` | `sources/` |
| `contact` | `Actor` | `actors/` |

The exporter writes `olca-schema.json` with `{"version": 2}` at the ZIP root.
Import also accepts the `openlca.json` manifest with `{"schemaVersion": 5}`
written by openLCA Desktop 2.6.2. Every dataset file is named `<uuid>.json`
and contains a matching `@id`.

## Export request

The core exporter accepts one JSON object containing these arrays:

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

Every row contains `id`, `type`, `name`, optional `description`, and `payload`.
The bundle must include every required Process, Flow, FlowProperty, and
UnitGroup reference. Missing required references fail the whole export.

## Model mapping

PRISM process instances become `ProductSystem.processes`. Connections become
`ProductSystem.processLinks`; the exporter infers each link's Flow and consumer
exchange from the provider's quantitative-reference output. The selected
reference process becomes `refProcess` and its quantitative-reference exchange
becomes `refExchange`.

openLCA ProductSystem does not directly represent a multiplication factor for
every process occurrence. The package therefore includes a namespaced
`otherProperties.prismInterchange` extension. It contains the original PRISM
payload and a hash of the standard openLCA fields. A package that returns
unchanged can recover the full PRISM representation. If an openLCA user edits
the standard fields, import ignores the stale extension and rebuilds the PRISM
payload from those edited fields.

Manual openLCA 2.6.2 round-trip acceptance confirmed that Desktop preserves
the supported Product System graph and all seven dataset types. Desktop
normalizes arbitrary Process-instance multiplication factors (observed from
`1`/`2` to `1`/`1` in JSON-LD), so exact factor preservation is not promised
after Desktop rewrites a package. A Desktop rewrite also invalidates the
private extension hash; import reports `STALE_PRISM_EXTENSION` and safely
rebuilds the payload from the standard openLCA fields.

## Import preview

Import never writes to Supabase. It returns normalized rows with a proposed
decision:

- `create` for a new UUID and name;
- `update` for an existing UUID;
- `review` for the same normalized type and name under a different UUID.

Unknown openLCA root types are ignored with warnings. Missing referenced rows
are reported as warnings so the user can review an incomplete external package.

## Safety limits

The initial core defaults are 25 MB compressed, 250 MB expanded, and 5,000 ZIP
entries. Absolute paths, parent traversal, backslash paths, and symbolic links
are rejected before any member is read. HTTP-level streaming limits and request
timeouts belong to delivery batch 4.
