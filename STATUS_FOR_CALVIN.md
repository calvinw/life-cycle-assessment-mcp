# openLCA JSON-LD and ILCD Import — Status & Approval Request

## Goal
Let a PRISM user upload an openLCA JSON-LD or ILCD/eILCD ZIP and see it loaded
into the webapp workspace immediately — no database writes, import only. Full
designs are in `ENGINE_IMPORT_EXPORT_PLAN.md` and `ILCD_IMPORT_PLAN.md` on this
branch.

## What's done

**Engine (`calvinw/life-cycle-assessment-mcp`):**
- `lca_core.interchange`: openLCA ZIP → PRISM dataset conversion, with path-traversal, entry-count, compressed-size, and expanded-size checks.
- New route: `POST /api/interchange/import/openlca`.
- CORS: added `https://catiehe.github.io` (PRISM production origin) to the allowlist in `sse_server.py`.
- An oversized upload (>25MB) is rejected by `Content-Length` before its body is read.
- Verified locally end to end against a running server: import succeeds, CORS preflight passes for the PRISM origin and is rejected for others, oversized uploads get a clean `413`.
- Added automatic ILCD/eILCD detection and conversion through the same route,
  verified against a real openLCA Desktop export. All seven PRISM dataset types
  are supported; lifecycle-model links are flattened into PRISM connections.
- Shared the ZIP safety checks between both formats and enforce the compressed
  size limit while streaming even if `Content-Length` is absent or inaccurate.

**Frontend (`catiehe/tiangong-simple`, `main`):**
- File picker → upload → summary/warnings/errors preview → per-type tables → click into an imported Model and view it read-only through the existing `ModelDetail` component. Everything stays in React state; nothing is written to Supabase.
- Fixed a bug where warning/error objects from the engine were rendered as if they were plain strings (would have crashed on the first real import with any warning).

## What's NOT done yet
- The JSON-LD reader is not yet tested against a real openLCA Desktop JSON-LD
  export, only engine-generated packages. The ILCD reader does have a real
  Desktop fixture.
- Upload is still raw bytes, not `multipart/form-data` as the documented contract specifies.
- No request timeout or concurrency limit on the import route yet.
- Frontend doesn't wire into a calculation flow (this webapp has no calculation engine to call yet — separate future feature).

## The blocker: production deployment
The first openLCA JSON-LD release is on `main` and is deployed successfully at
`https://lca.mathplosion.com`: the route, CORS, and a real import request all
pass. The ILCD extension remains on `catie-import-feature` pending review.

**The documented frontend API host (`https://lca-mcp.mathplosion.com`) is still
running the old code**, while the deployment script targets
`https://lca.mathplosion.com`. Confirmed after the first deployment:

```
POST /api/interchange/import/openlca  →  404 Not Found
CORS preflight from catiehe.github.io →  rejected, no allow-origin header
```

## Ask
1. Review and approve the ILCD commit on `catie-import-feature`.
2. Merge and deploy it using the existing deployment script.
3. Point the PRISM frontend at `https://lca.mathplosion.com`, or update the
   `lca-mcp.mathplosion.com` reverse proxy to serve the same deployment.

Once that's live, the import flow at `catiehe.github.io/tiangong-simple/import`
should work end to end.
