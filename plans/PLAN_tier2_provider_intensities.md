# Plan: Tier 2 — Return Background Provider Intensities from Call 1

Status: Phases 1-4 complete and green on `plan/tier2-provider-intensities`,
ready to merge and deploy;
consumed end to end by the Realtime view and confirmed by hand against an
independently running copy of the webapp. Phases 3 and 4 remain open. Tier 2 was
authorised by explicit instruction on August 18, 2026  
Date: August 18, 2026  
Parent plan: [`PLAN_precomputed_background_intensities.md`](PLAN_precomputed_background_intensities.md)  
Plain-English overview: [`explainer_precomputed_background_intensities.md`](explainer_precomputed_background_intensities.md)  
Coordinated frontend plan:
[`product-graph-editor/plan/realtime-scenario-view.md`](../../product-graph-editor/plan/realtime-scenario-view.md)

## Goal

Attach the cached cumulative intensity of every resolved background provider to
the Call 1 response, so the product editor can update impact-category scores
locally while a user drags a background input amount. The exact server
calculation stays the source of truth and still runs on release.

## Authorised scope

Tier 2 was gated on explicit instruction in three places. That instruction was
given. The agreed v1 slider scope is **background input amounts only**.

| Slider | In v1 | Extra payload required |
|---|---|---|
| Background input amount | yes | provider intensities |
| Reference output / yield | no | none, but requires a browser-side foreground re-solve |
| Emission / resource amount | no | per-flow characterization factors |
| Provider swap | no | intensity for a provider absent from the graph |

Yield and emission sliders are deliberately deferred. The explainer promises an
emission slider; that promise needs a characterization-factor payload which
this plan does not add. Record that gap rather than implying v1 covers it.

## Why v1 needs exactly one new field

Holding foreground structure fixed and varying only background input amounts
leaves the foreground scaling vector `s_F` unchanged. The score is therefore
exactly linear in the edited amounts:

```text
score_new = score_baseline
          + Σ  s_F(consumer) × (amount_new − amount_baseline) × y_B(provider)
```

Every term except `y_B` is already in the Call 1 response:

- `scaling_vector` supplies `s_F(consumer)` — `lca_core/engine.py:1289`.
- `lcia[label].score` supplies `score_baseline`.
- The edited amounts belong to the browser's own YAML.

The resolved-provider identity also already exists server-side.
`_build_foreground_db` returns `background_providers` keyed by
`(process_index, input_index)` — `lca_core/engine.py:713` — and `_run_analysis`
already threads it through for the Sankey. Tier 2 reuses that key rather than
inventing a new one.

## New Call 1 cost

`run_base_analysis` calls `_run_analysis(include_contribution_graphs=False)`, so
`contribution_methods` is empty and the background intensity cache is **never
consulted in Call 1 today**. Tier 2 introduces the first Call 1 cache read: one
`get_background_y` lookup per calculation method. Warm, this is a dictionary
lookup. Cold, it is one back-solve per category, which is the cost Tier 1
already characterised.

## Contract change

### New types in `lca_core/models.py`

```python
class BackgroundLinkIntensity(TypedDict):
    link_id: str            # stable id derived from process/input index
    process_index: int
    input_index: int
    process_name: str
    flow: str
    database: str
    code: str
    location: str | None
    amount: float           # baseline amount from the spec
    unit: str
    intensities: dict[str, float]   # category label -> cumulative intensity
```

`LcaCoreResult` gains:

```python
background_link_intensities: NotRequired[list[BackgroundLinkIntensity]]
```

The descriptive fields (`database`, `code`, `flow`, `location`) let the editor
reuse its existing `backgroundKeyFor` identity. `process_index` and
`input_index` remain the authoritative key.

### Schema version

`result_schema_version` stays `3`. The field is additive and optional, and the
editor gates on `result_schema_version !== 3` at `src/lib/lcaApi.ts:245`.
Keeping `3` means an updated editor still works against a server without the
field, and an old editor still works against a server with it. The editor
feature-detects the field's presence instead. Bumping to `4` would force a
lockstep deploy for no contract benefit.

### Cache-mode coupling

Populate `background_link_intensities` only when
`background_intensity.effective_mode() != "off"`. The field is the cache made
visible; with the cache off there is nothing exact to publish, and the editor
must fall back to server round-trips. Production already runs `on`; the
committed default is still `off`, so the field is absent by default.

If the cache disables itself mid-process, later responses simply omit the field.
The editor must treat disappearance as a normal fallback, not an error.

## Reconciliation invariant

This is the gate. For every calculated category:

```text
total_score − Σ (foreground direct_score)
    ==  Σ_links  s_F(consumer) × amount_baseline × y_B(provider)
```

The left side comes from `process_contributions` — `_contribution_category`
already emits an exact exclusive `direct_score` per foreground process
(`lca_core/engine.py:812`) and reconciles it against `total_score`. The right
side is the arithmetic the browser will perform.

This validates the entire Tier 2 payload end to end using only Call 1 output,
and it validates it with the same formula the frontend uses.

### Tolerance: the float32 amount floor

Measured finding, not an estimate. **Brightway stores technosphere exchange
amounts as float32.** A YAML amount of `0.52` is held in the matrix as
`0.5199999809265137`. The server therefore scores with float32-rounded amounts,
while the invariant above — and the editor — multiply the exact float64 amount
from the spec.

The residual is bounded by float32 epsilon, `1.19e-7`. Measured residuals across
the bundled background-linked graphs run from `1.1e-8` to `5.8e-8`, and appear
with both signs, which is the signature of rounding rather than a missing term.
The invariant therefore uses a relative tolerance of `1e-6`, an order of
magnitude above the storage floor and still far below anything the UI displays
at five decimal places.

This floor is **not** cache error. Cached intensities were verified
bit-identical to a full request-matrix adjoint solve — maximum relative
difference exactly `0.0` across 11,760 background product nodes on the BAFU
broom. Tier 1's own `on`-mode reconciliation (`cached @ demand` versus
`lca.score`) agrees to `1.9e-11` and is unaffected, because both of its sides
read the same stored float32 amounts.

Consequence for the editor: a local preview and the exact refresh can never
agree to better than roughly `1e-7` relative. The editor's drift check must be
set from this floor, not from the `1e-8` adjoint tolerance.

## Phases

### Phase 1 — payload

Add the types, populate the field in the `_run_analysis` category loop after
`lca.lcia()`, and confirm the provider node id used as the `get_background_y`
key is the product node id the cache is keyed on. Extend
`_ensure_finite_result` coverage implicitly; new floats already pass through it.

### Phase 2 — reconciliation tests

New `tests/test_tier2_provider_intensities.py`:

- reconciliation invariant across every configured category for all six product
  graphs that declare background links;
- exactness of the linear prediction: perturb one background amount, predict via
  the formula, run the real calculation, and compare;
- field absent when the cache mode is `off`;
- indices in the payload address the same exchanges as the source YAML;
- graphs with no background links return an empty list, not a missing field.

The canonical spec paths are the ones the existing suite uses, in
`tests/background_intensity_helpers.py`: `BACKGROUND_LINKED_PATHS` holds the
seven graphs with background links (four `bafu_examples/`, three
`mock_examples/`), and the remainder of `ALL_SPEC_PATHS` — the four
`case_studies/` graphs — are the foreground-only empty-list cases. The
`product-graphs/` directory is the editor-facing catalogue served by
`GET /api/product-graphs`, not the test corpus.

### Phase 3 — measure — DONE

Recorded in [`../benchmarks/tier2_call1_payload.md`](../benchmarks/tier2_call1_payload.md)
using `scripts/benchmark_tier2_call1.py`, which follows the Tier 1 seven-sample
method. A `background_link_intensities_per_category` phase was added to Call 1
instrumentation to isolate the new work.

| Configuration | Link phase median | Call 1 wall median |
|---|---:|---:|
| `off` baseline | 0.013ms | 811.824ms |
| `on`, warm | 0.044ms | 830.131ms |
| `on`, category miss | 8.126ms | 810.255ms |
| `on`, full rebuild | 627.502ms | 1477.273ms |

**The warm cost is 0.031ms** — 0.044 minus the 0.013 no-op — for three links
across two categories, roughly 5µs per link-category.

The wall column is not a Tier 2 signal. `on` warm reads 18ms above `off`, but
`on` with a category miss — strictly more work — reads *below* both. Call 1 wall
time is dominated by temporary foreground creation, which spanned 304-418ms
across samples. Attributing that 18ms swing to Tier 2 would overstate its cost
by roughly 600x.

The full-rebuild row is synthetic: it clears the LU factorization so every
sample re-runs `_build_entry`. Operationally that happens at startup or on a
background database identity change, not per request.

### Phase 4 — documentation — DONE

`docs/rest_api.md` and `docs/llm_rest_api_guide.md` now document the field, its
cache-mode conditionality, the `(process_index, input_index)` key, the local
rescoring formula, and the float32 tolerance guidance for clients.

Update `docs/llm_rest_api_guide.md` and `docs/rest_api.md` with the new field,
its cache-mode conditionality, and the reconciliation formula.

## What was actually built

`lca_core/models.py` gained `BackgroundLinkIntensity` and the optional
`background_link_intensities` entry on `LcaCoreResult`. `result_schema_version`
stayed at `3`.

`lca_core/engine.py` gained two helpers:

- `_background_link_rows(spec, background_providers)` describes every
  foreground/background link in stable spec order, reusing the
  `(process_index, input_index)` key `_build_foreground_db` already returns.
- `_attach_background_link_intensities(...)` adds one category's cached provider
  intensity to every row, returning `False` when the cache cannot supply that
  category.

`_run_analysis` builds the rows once, fills them inside the existing category
loop, and publishes the field only when **every** category succeeded. A partial
payload is never emitted: a client that received some categories but not others
would silently mis-score the missing ones. With the cache off, or after it
disables itself, the field is simply absent and the client falls back.

### Verified over HTTP

`POST /api/lca/base` for `bafu_examples/plastic_broom.yaml` against a local
server with `LCA_BACKGROUND_INTENSITY_CACHE=on` returns all three links with
both categories populated, correct provider codes, locations, and units.

### Confirmed by hand

The Realtime view's slider preview was compared against a separately running
copy of the webapp, where the same amount change was made through the ordinary
YAML edit and full calculation path. The two agree. This is an independent
end-to-end confirmation of the decomposition, obtained without the test
fixtures.

## Local testing recipe

Production still runs the Tier 1 commit, which has no Tier 2 field, and the
editor's Vite dev proxy points at production by default. Testing Realtime
therefore requires a local engine:

```bash
# engine — the cache flag is what publishes the field
BRIGHTWAY_PROJECT=lca_server BRIGHTWAY2_DIR=$PWD/brightway_data \
  LCA_BACKGROUND_INTENSITY_CACHE=on PORT=9000 .venv/bin/python sse_server.py

# editor, from ../product-graph-editor
VITE_LCA_API_BASE=http://localhost:9000 npm run dev
```

`http://localhost:5173` is already in the server's CORS allow-list, so no
configuration change is needed. Load `plastic_broom`; the catalogue default,
`jacket`, has no background links and lands on the empty state.

## Out of scope

- Tier 3 and any score-only foreground bypass;
- characterization-factor payload and emission sliders;
- yield sliders and browser-side foreground re-solve;
- a provider-swap intensity lookup endpoint;
- `result_id` caching and SVG changes.

## Stop conditions

Stop and report if the reconciliation invariant fails on any bundled graph, if
the provider node id does not key into the cached intensity mapping, if the
perturbation prediction does not match the exact calculation within policy
tolerance, or if Call 1 wall time regresses beyond roughly 20ms warm.

## Branch and dependency

Tier 1 is still unmerged to `main`; see
[`PLAN_2026-08-17_deploy_background_intensity_to_main.md`](PLAN_2026-08-17_deploy_background_intensity_to_main.md).
Tier 2 depends on the Tier 1 cache, so it branches from
`plan/background-intensity-feasibility`. Merging Tier 1 to `main` first remains
the preferred order and is tracked by that plan, not this one.

## Definition of done

- [x] Types added and populated
- [x] Field conditional on effective cache mode
- [x] Reconciliation invariant green on all seven background-linked graphs
- [x] Perturbation prediction matches exact calculation within tolerance
- [x] Empty-list behaviour verified on foreground-only graphs
- [x] Full suite green in `off` and `compare` modes, 80 tests
- [x] Field verified over HTTP on a local server
- [x] Frontend plan's contract expectations confirmed against the shipped field
- [x] Preview confirmed by hand against an independent full calculation
- [x] Call 1 cost measured and recorded in absolute milliseconds
- [x] REST documentation updated
- [x] Tier 1 merged to `main` and deployed (`47d9cb9`, August 18, 2026)
- [ ] Tier 2 merged to `main` and deployed
- [ ] Editor `realtime` branch merged and shipped

## Known unrelated failure

`tests/test_performance_instrumentation.py` asserts
`adjoint_transpose_factorization` appears in the Call 2 phases. Tier 1 in `on`
mode deliberately removes that phase, so this test fails under
`LCA_BACKGROUND_INTENSITY_CACHE=on` both with and without the Tier 2 change.
It predates Tier 2 and belongs to Tier 1; production runs `on`, so it should be
made mode-aware, but not under this plan.
