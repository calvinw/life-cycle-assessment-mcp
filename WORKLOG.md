# Work Log

## 2026-09-15
- Implemented ILCD/eILCD import end to end from the real openLCA Desktop
  fixture: all seven PRISM dataset converters, lifecycle-model graph
  flattening, shared ZIP safety checks, automatic format dispatch through the
  existing route, stable route errors, and focused core/HTTP/CORS tests. The
  real fixture returns 1 Model, 4 Processes, 6 Flows, 4 Unit Groups, and all
  four expected flattened connections. A second user-generated hybrid export
  (ILCD XML plus openLCA-shaped JSON folders but no manifest) is also accepted
  through the ILCD path with an explicit warning. Production deployment of the
  ILCD extension remains pending.
- Added a minimal `POST /api/interchange/import/openlca` route in `lca_server.py` on top of the existing `lca_core.interchange` openLCA JSON-LD converter, plus the PRISM production CORS origin and an early `Content-Length` size guard in `sse_server.py`. Verified locally end to end (curl against a running server): happy-path import, CORS allow/deny, oversized-upload `413`. See `ENGINE_IMPORT_EXPORT_PLAN.md` (Batch 3, started).
- Wrote `PRISM_FRONTEND_IMPORT_PLAN.md` as a self-contained handoff doc for the `catiehe/tiangong-simple` frontend. That work happened there, not here: it shipped a file-picker import preview (F1–F3 of that doc), and a same-day bug fix after a review here caught that the engine's real `warnings`/`errors` are `{code, message, details}` objects, not strings — the frontend had typed/rendered them as `string[]` and would have crashed on the first real import warning.
- Wrote `STATUS_FOR_CALVIN.md`: the engine changes only exist on this branch (`catie-import-feature`), not merged to `main`, and production (`https://lca-mcp.mathplosion.com`) is still on the old code — confirmed via a live curl (404 on the new route, CORS still rejects the PRISM origin). **Blocked on Calvin approving the merge and redeploying production.** Nothing else needed to make the openLCA import path usable.
- Started scoping a second import format: ILCD/eILCD (the format openLCA Desktop's other export option produces — a real user-provided sample turned out not to be JSON-LD). Wrote `ILCD_IMPORT_PLAN.md` and `docs/ilcd_interchange_contract.md`, grounded in a real sample now checked in as `tests/fixtures/ilcd_plastic_broom.zip`. **Batch A only (contract + fixture + mapping decisions) — no converter code yet.**

### Where to pick this up next
- If Calvin has approved/deployed: re-verify the openLCA import path against production (the curl checks in `STATUS_FOR_CALVIN.md`), then close that out.
- ILCD work resumes at **Batch B** in `ILCD_IMPORT_PLAN.md`: add `lca_core/interchange/ilcd.py`, starting with Flow/Process/UnitGroup conversion (present in the real fixture and testable immediately), then FlowProperty/Source/Contact, then the Model/graph flattening (nested `processInstance/connections` → PRISM's flat `connections` list) last, since that's the hardest part.
