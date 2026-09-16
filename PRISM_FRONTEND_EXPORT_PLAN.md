# PRISM Frontend: openLCA and ILCD Export — Handoff Plan

For whoever picks up the PRISM webapp side of the Export feature (the
counterpart to `PRISM_FRONTEND_IMPORT_PLAN.md`, which you should have already
built). The backend (this repo, `calvinw/life-cycle-assessment-mcp`) has a
working export endpoint with a full automated test suite behind it. This
document is everything you need to build the frontend half without reading
the backend plan (`INTERCHANGE_EXPORT_PLAN.md` in that repo, if you want the
full background).

Last updated: 2026-09-15

## What already works today — and what doesn't yet

A PRISM workspace bundle (Model + Processes + Flows + Flow Properties + Unit
Groups + Sources + Contacts, the same seven types you already handle on
import) can be sent to the engine as JSON and converted into a downloadable
openLCA JSON-LD or ILCD/eILCD ZIP. The backend's automated suite covers both
formats, multi-Process graphs, and atomic validation failures. Both formats
have also passed a real local HTTP export followed by HTTP re-import with all
seven dataset types, no warnings, and no errors. The ILCD/eILCD package passed
manual openLCA 2.6.2 import and Desktop re-export acceptance with all seven
supported dataset types and the Process graph connection intact. JSON-LD also
passed openLCA 2.6.2 import and Desktop re-export acceptance. openLCA normalized
Process-instance multiplication factors to `0.0` in ILCD and `1.0` in JSON-LD;
these target-format limitations are recorded in the interchange contracts.

**This export work is not merged to `main` yet and is not deployed anywhere**
(it's uncommitted on the `catie-import-feature` branch as of this writing).
Don't point any frontend build at a production URL for this feature until the
backend owner confirms it's merged and deployed — check with them first, the
same way the import feature was gated on Calvin's approval.

## The endpoint

```
POST /api/interchange/export
Content-Type: application/json
```

- Local dev, once deployed: same host/port pattern as the import endpoint
  (`http://localhost:9000` for `sse_server.py` locally). Confirm the
  production host with the backend owner before using it — see caveat above.
- **Unlike import, this is a JSON body, not raw file bytes.**

Request:

```json
{
  "format": "openlca-json-ld",
  "model_id": "optional-model-uuid",
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

```js
const response = await fetch(EXPORT_URL, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ format, model_id: modelId, datasets: bundle }),
});
```

- `format` — required. Either `"openlca-json-ld"` or `"ilcd-xml"`.
- `model_id` — optional. When present, the server computes the transitive
  dependency closure for that Model and exports only those records — you can
  send your **entire** in-memory workspace and let the server figure out what
  belongs in the package. Omit it to export exactly the bundle you send
  as-is (useful for a "export everything" action, if you ever add one).
- `datasets` — an object keyed by the **plural** type name (`models`,
  `processes`, `flows`, `flow_properties`, `unit_groups`, `sources`,
  `contacts`), each an array of rows shaped like:

  ```json
  {
    "id": "b6f1...-uuid",
    "type": "flow",
    "name": "Steel",
    "description": "Steel product",
    "payload": { "...": "ILCD-like JSON, same shape as import's row.payload" }
  }
  ```

  **`id` must be a real UUID** (the server validates the format strictly) and
  unique across the whole bundle. `name` is required and non-blank.
  `description` is optional. `payload` is the same ILCD-like JSON object
  shape you already receive back in `row.payload` from the import endpoint —
  see the note below on where this data comes from.

Success response (`200`):

```
Content-Type: application/zip
Content-Disposition: attachment; filename="prism-export.openlca.zip"
```
(or `prism-export.ilcd.zip` for the ILCD format)

Read the response as a blob and trigger a download:

```js
const blob = await response.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
// Don't rely on reading the Content-Disposition header — see caveat below.
a.download = format === "openlca-json-ld" ? "prism-export.openlca.zip" : "prism-export.ilcd.zip";
a.click();
URL.revokeObjectURL(url);
```

Failure response (`400` / `413` / `422`):

```json
{ "error": { "code": "UNSUPPORTED_EXPORT_FORMAT", "message": "Export format must be 'openlca-json-ld' or 'ilcd-xml'.", "details": {} } }
```

Show `error.message` to the user. Notable stable codes worth branching on:

| Code | Meaning |
| --- | --- |
| `UNSUPPORTED_EXPORT_FORMAT` | `format` wasn't one of the two supported values |
| `UNKNOWN_EXPORT_MODEL` | `model_id` doesn't match any Model in `datasets` |
| `EMPTY_BUNDLE` | `datasets` had no records in it at all |
| `INVALID_DATASET_ID` / `DUPLICATE_DATASET_ID` | a row's `id` isn't a valid/unique UUID |
| `MISSING_DATASET_NAME` | a row is missing a non-blank `name` |
| a reference/closure error (e.g. unresolved Process/Flow reference) | the bundle is internally inconsistent — a dependency is missing |
| `EXPORTED_PACKAGE_TOO_LARGE` | generated ZIP exceeds the 25 MB limit |

All of these mean the export failed **atomically** — nothing partial is ever
returned. If you get one of these on a bundle built from data the user
imported and never touched, that's a backend bug, not a frontend one — report
it rather than trying to work around it.

### The open question this doc can't answer for you

The `payload` field per dataset type is the same shape the import endpoint
already puts into `row.payload` (see `PRISM_FRONTEND_IMPORT_PLAN.md` Step
F3) — an ILCD-like JSON object with fields like `processInformation`,
`exchanges`, `flowInformation`, etc. **If a Model was imported and never
edited, you can round-trip it by sending its rows back unchanged** — that's
the easy case and should work today.

**If a Model was created or edited natively in the PRISM UI**, you'll need to
produce that same `payload` shape from PRISM's own internal representation.
This repo doesn't know what PRISM's native Model/Process/Flow schema looks
like, so it can't tell you how big that mapping is. Two references that may
help:

- `docs/openlca_interchange_contract.md` and `docs/ilcd_export_contract.md`
  in this repo document the exact fields the payload can contain.
- Whatever shape your F3 in-memory workspace already normalizes imported
  data into — if you kept `row.payload` around unchanged after import, that's
  already a valid producer for this endpoint.

If PRISM's native editor works in a completely different internal shape,
scope that translation work before committing to a timeline — it's likely
the largest unknown in this feature, bigger than the fetch/download plumbing.

## CORS caveat: don't try to read the filename header

The response's `Content-Disposition` header **is not exposed to browser
JavaScript** under the current CORS config (only `Mcp-Session-Id` is in
`expose_headers`). `response.headers.get('content-disposition')` will return
`null` even though the header is present on the wire. This isn't a bug worth
filing — the filename is fully deterministic
(`prism-export.<openlca|ilcd>.zip`), so just hardcode it client-side based on
the `format` you sent, as shown above.

CORS origins are otherwise already allowlisted the same way as import:
`https://catiehe.github.io` (production) and `http://localhost:5173` (dev).

## Suggested build order (each step should be independently demoable)

### Step G1 — Prove the network round-trip
Build one hardcoded request body (small bundle, `model_id` omitted) and
`fetch` it against a locally running engine. Confirm you get back a `200`
with `application/zip` and that the bytes are a valid ZIP
(`new JSZip().loadAsync(blob)` or similar).

**Done when:** a hardcoded request downloads a ZIP with no CORS error.

### Step G2 — Export an imported-and-untouched Model
Wire up "export the Model currently in the F3 in-memory workspace" using its
existing `row.payload` values unchanged, with `model_id` set to that Model's
id and the rest of the workspace's rows sent alongside it for closure
resolution. Add a format picker (openLCA JSON-LD / ILCD).

**Done when:** you can import a ZIP, then re-export it in either format, and
the resulting file opens as a valid ZIP with the expected dataset counts.

### Step G3 — Export a natively-created/edited Model
This is where the open question above gets resolved — translate PRISM's own
Model/Process/Flow state into the `payload` shape the endpoint expects.

**Done when:** a Model built entirely in the PRISM UI (never imported)
exports successfully in both formats.

### Step G4 — Error handling and UX polish
Render `error.message` on failure. Optionally branch on `error.code` for a
friendlier message (e.g. explain `UNKNOWN_EXPORT_MODEL` as "select a Model
before exporting"). Add a loading/progress state — large bundles may take a
moment to serialize.

**Done when:** a deliberately broken bundle (e.g. a Model referencing a
deleted Process) shows a clear, non-crashing error instead of a silent
failure.

### Step G5 (optional / stretch)
Let the user pick which Model to export from a list instead of always
exporting "the current one." Batch-export multiple Models. Not required for
a first cut.

## What NOT to build yet

- Persistence of exported files (this is a stateless download, not a saved
  artifact).
- Editing a bundle after building it but before sending it — fix the source
  data instead.
- EcoSpold, SimaPro CSV, or any format beyond the two supported here.
- Merge/conflict UI — export doesn't touch Supabase or any server-side state.
- Trusting a generated file as "openLCA Desktop compatible" for anything
  user-facing/production until the backend owner confirms Desktop acceptance
  testing (`INTERCHANGE_EXPORT_PLAN.md` Step E6) has actually happened. Until
  then, treat both formats as "passes our own round-trip tests," not "proven
  interoperable."

## If something looks broken

- CORS error → confirm you're calling the exact allowlisted origin, and that
  you're not trying to read `Content-Disposition` from JS (see caveat above).
- A reference/closure error on a bundle you believe is complete → you're
  probably missing a dependency in `datasets` (e.g. a Flow's `flow_property`
  isn't included) or `model_id` points at something not present in the
  bundle you sent — send the whole workspace, not just the one Model's row.
- Anything else → send the exact request (redact nothing except real
  production data) to the backend owner rather than guessing. This endpoint
  is new; there may be a code or edge case the automated tests haven't hit
  yet.
