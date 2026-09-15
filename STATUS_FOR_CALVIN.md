# openLCA Import — Status & Approval Request

## Goal
Let a PRISM user upload an openLCA JSON-LD ZIP and see it loaded into the
webapp workspace immediately — no database writes, import only. Full design
in `ENGINE_IMPORT_EXPORT_PLAN.md` on this branch.

## What's done

**Engine (`calvinw/life-cycle-assessment-mcp`, branch `catie-import-feature`, not yet merged to `main`):**
- `lca_core.interchange`: openLCA ZIP → PRISM dataset conversion, with path-traversal, entry-count, compressed-size, and expanded-size checks.
- New route: `POST /api/interchange/import/openlca`.
- CORS: added `https://catiehe.github.io` (PRISM production origin) to the allowlist in `sse_server.py`.
- An oversized upload (>25MB) is rejected by `Content-Length` before its body is read.
- Verified locally end to end against a running server: import succeeds, CORS preflight passes for the PRISM origin and is rejected for others, oversized uploads get a clean `413`.

**Frontend (`catiehe/tiangong-simple`, `main`):**
- File picker → upload → summary/warnings/errors preview → per-type tables → click into an imported Model and view it read-only through the existing `ModelDetail` component. Everything stays in React state; nothing is written to Supabase.
- Fixed a bug where warning/error objects from the engine were rendered as if they were plain strings (would have crashed on the first real import with any warning).

## What's NOT done yet
- Not tested against a real openLCA Desktop export, only engine-generated packages.
- Upload is still raw bytes, not `multipart/form-data` as the documented contract specifies.
- No request timeout or concurrency limit on the import route yet.
- Frontend doesn't wire into a calculation flow (this webapp has no calculation engine to call yet — separate future feature).

## The blocker: production deployment
The engine changes only exist on `catie-import-feature`. **Production
(`https://lca-mcp.mathplosion.com`) is still running the old code** — confirmed
just now:

```
POST /api/interchange/import/openlca  →  404 Not Found
CORS preflight from catiehe.github.io →  rejected, no allow-origin header
```

## Ask
1. Review and approve merging `catie-import-feature` into `main`.
2. Deploy the updated engine to `lca-mcp.mathplosion.com`.

Once that's live, the import flow at `catiehe.github.io/tiangong-simple/import`
should work end to end.
