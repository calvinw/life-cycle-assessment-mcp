# PRISM Frontend: openLCA Import — Handoff Plan

For whoever picks up the PRISM webapp side of the openLCA import feature.
The backend (this repo, `calvinw/life-cycle-assessment-mcp`) already has a
working import endpoint. This document is everything you need to build the
frontend half without reading the backend plan (`ENGINE_IMPORT_EXPORT_PLAN.md`
in that repo, if you want the full background).

Last updated: 2026-09-15

## What already works today

A user's openLCA JSON-LD ZIP can be uploaded to the engine and converted into
PRISM-shaped datasets. This has been verified against a running local server:
CORS, the size limit, and the conversion itself all behave correctly.

**PRISM's production origin (`https://catiehe.github.io`) and local dev
(`http://localhost:5173`) are already on the engine's CORS allowlist.** You
can call the endpoint from the browser without asking the backend for
anything else.

## The endpoint (as it exists right now — read the caveats below)

```
POST /api/interchange/import/openlca
```

- Local dev: `http://localhost:9000/api/interchange/import/openlca` (default
  port for `sse_server.py`; ask the backend owner for the current deployed
  URL, e.g. `https://lca-mcp.mathplosion.com/...`, for a staging/production test).
- **Body: the raw ZIP file bytes.** Not `multipart/form-data` yet — that's
  planned but not built. Send the file directly as the request body:

  ```js
  const response = await fetch(IMPORT_URL, {
    method: "POST",
    body: fileObjectFromInput, // a File/Blob works directly as a fetch body
  });
  const result = await response.json();
  ```

- Response on success (`200`):

  ```json
  {
    "format": "openlca-json-ld",
    "valid": true,
    "summary": { "model": 1, "process": 1, "flow": 1, "flow_property": 1, "unit_group": 1, "source": 1, "contact": 1 },
    "datasets": [
      { "id": "...", "type": "flow", "name": "Steel", "description": "Steel product", "payload": { /* ILCD-like JSON */ }, "decision": "create", "temporary_id": "...", "source_id": "..." }
    ],
    "matches": [],
    "warnings": [],
    "errors": []
  }
  ```

  `datasets` is a **flat array mixing all seven types** — filter/group it by
  `row.type` client-side (`model`, `process`, `flow`, `flow_property`,
  `unit_group`, `source`, `contact`). Ignore `matches` and `decision` — those
  are leftover fields from an older database-conflict design and are not
  meaningful for this stateless import; the backend will drop them in a
  later revision.

- Response on failure (`400` / `413` / `422`):

  ```json
  { "error": { "code": "PACKAGE_TOO_LARGE", "message": "The compressed package exceeds the 25 MB limit.", "details": { } } }
  ```

  Show `error.message` to the user; `error.code` is stable if you ever want
  to branch on it (e.g. a friendlier message for `PACKAGE_TOO_LARGE`).

### Known caveats — don't design around these as if they're final

1. **Response shape will change.** The backend still returns the legacy flat
   `datasets` array shown above. A future revision groups it into
   `datasets: { models: [], processes: [], flows: [], ... }`. Isolate the
   fetch call behind one function (e.g. `importOpenLcaPackage(file)`) so that
   change is a one-file fix, not a rewrite.
2. **No multipart yet.** If the backend later switches to
   `multipart/form-data`, you'll change the `fetch` body from raw bytes to a
   `FormData` with a `file` field. Same isolation advice applies.
2. **No real openLCA Desktop package has been tested yet**, only
   engine-generated ones. Don't be surprised if a real Desktop export
   surfaces a new warning/error code the backend hasn't seen before — treat
   the `warnings`/`errors` arrays as things you must render, not edge cases
   you can ignore.
3. **Nothing persists.** Closing or refreshing the page loses the imported
   data. That's intentional for this first release — don't add
   IndexedDB/localStorage persistence unless separately asked for.

## Suggested build order (each step should be independently demoable)

Mirrors how the backend was built: small steps, each one actually runnable
before moving to the next.

### Step F1 — Prove the network round-trip
Add a file `<input type="file">` somewhere reachable (a hidden dev route is
fine). On file select, `fetch` it to the import endpoint and
`console.log(await response.json())`. No UI, no state.

**Done when:** picking a `.zip` in the browser logs the parsed JSON in
devtools, no CORS error.

### Step F2 — Show a plain summary
Render `result.summary` as a simple counts table and `result.warnings` /
`result.errors` as a list. Still no app state — this can be a throwaway
component.

**Done when:** a non-technical user could pick a file and see "5 flows, 2
processes, 0 errors" on screen.

### Step F3 — Load into a temporary workspace
Put `result.datasets` (grouped by `type`) into React state — a temporary,
in-memory workspace, separate from whatever state backs the saved
`datasets` table. Pass at least one imported Model into the **existing**
viewing component read-only.

**Done when:** an imported Model's structure renders using the app's normal
Model view, without touching Supabase.

### Step F4 — Wire into calculation
Let the user trigger the existing calculation flow against an imported
Model/Process, using the imported data directly (no save-then-load round
trip through the database).

**Done when:** you can import a ZIP and get a calculation result end to end,
purely in the browser session.

### Step F5 (optional / stretch)
Upload progress indicator, nicer error messages keyed off `error.code`,
editing imported records before calculating. Not required for a first cut —
only do this once F1–F4 work.

## What NOT to build yet

- Any persistence (Supabase, IndexedDB) of imported data.
- Merge/conflict UI ("this flow already exists, overwrite or skip?").
- Export (PRISM → openLCA). Not part of this feature.
- Authentication for the import endpoint — it's public and stateless by
  design for now.

## If something looks broken

- CORS error in the browser console → confirm you're calling the exact
  origin that's allowlisted (`https://catiehe.github.io` in production,
  `http://localhost:5173` in dev — a different port won't match).
- `413` on a small file → you're likely sending the file wrapped in
  something other than raw bytes (e.g. base64-encoded inside JSON). Send the
  `File`/`Blob` directly as the fetch body.
- Anything else → send the exact request (URL, headers, first ~200 bytes of
  the response) to the backend owner rather than guessing; the error
  contract above is deliberately in flux and there may be a code the
  frontend hasn't seen yet.
