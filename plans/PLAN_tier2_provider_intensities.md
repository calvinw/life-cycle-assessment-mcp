# Plan: Tier 2 — Return Background Provider Intensities from Call 1

Status: Phase 1 and Phase 2 implemented and green on
`plan/tier2-provider-intensities`; Tier 2 authorised by explicit instruction on
August 18, 2026  
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

### Phase 3 — measure

Record the added Call 1 cost, warm and cold, in
`benchmarks/tier2_call1_payload.md`. Report absolute milliseconds. Tier 2's
purpose is not a faster Call 1, so a small regression is acceptable and must be
stated rather than hidden.

### Phase 4 — documentation

Update `docs/llm_rest_api_guide.md` and `docs/rest_api.md` with the new field,
its cache-mode conditionality, and the reconciliation formula.

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
- [ ] Call 1 cost measured and recorded in absolute milliseconds
- [ ] REST documentation updated
- [ ] Frontend plan's contract expectations confirmed against the shipped field

## Known unrelated failure

`tests/test_performance_instrumentation.py` asserts
`adjoint_transpose_factorization` appears in the Call 2 phases. Tier 1 in `on`
mode deliberately removes that phase, so this test fails under
`LCA_BACKGROUND_INTENSITY_CACHE=on` both with and without the Tier 2 change.
It predates Tier 2 and belongs to Tier 1; production runs `on`, so it should be
made mode-aware, but not under this plan.
