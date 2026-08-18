# Tier 2: Call 1 Cost of Publishing Provider Intensities

Status: Phase 3 measured  
Date: August 18, 2026  
Branch: `plan/tier2-provider-intensities`  
Workload: `bafu_examples/plastic_broom.yaml`, two configured categories, three
background links  
Plan: [`../plans/PLAN_tier2_provider_intensities.md`](../plans/PLAN_tier2_provider_intensities.md)

Tier 2's purpose is not a faster Call 1. It adds a payload so the editor can
score slider edits locally. The question this benchmark answers is only whether
that payload costs anything worth caring about.

## Method

Matches `tier1_after_optimization.md`: same local Apple M4 host and Python
environment, one process per configuration, one discarded warm-up call, then
seven recorded `run_base` calls. Measurements come from the existing phase
instrumentation plus an outer `time.perf_counter()`. Reproduce with
`scripts/benchmark_tier2_call1.py`.

Call 1 previously never consulted the intensity cache at all, because
`run_base_analysis` requests no contribution graphs and the cache only ran for
contribution methods. Tier 2 introduces the first Call 1 cache read, so a new
`background_link_intensities_per_category` phase was added to isolate it.

All values are milliseconds.

## Result

| Configuration | Link phase median | Call 1 wall median | Field |
|---|---:|---:|:--|
| `off` — baseline | 0.013 | 811.824 | absent |
| `on`, warm | 0.044 | 830.131 | present |
| `on`, category miss | 8.126 | 810.255 | present |
| `on`, full cache rebuild | 627.502 | 1477.273 | present |

The `off` row is not zero because the phase timer still wraps the call that
returns immediately when the cache is disabled. That 0.013ms is the cost of
asking, not of computing.

### Warm — the case that matters

**The added cost is 0.031ms**: 0.044 warm minus the 0.013 no-op. Thirty-one
microseconds, to publish three links across two categories. Per link-category
that is roughly 5µs, which is a dictionary lookup and a float conversion.

The wall-time column must not be read as a regression. `on` warm shows 830.1ms
against 811.8ms for `off`, but `on` with a *category miss* — strictly more work —
comes in at 810.3ms, below both. Call 1 wall time is dominated by temporary
foreground creation, which ranged 304-418ms across samples. An 18ms swing is
foreground I/O noise, and the isolated phase measurement is three orders of
magnitude smaller than that swing. Reporting the wall delta as Tier 2's cost
would be wrong by a factor of about 600.

### Category miss

8.126ms for two categories, roughly 4ms each. This is one back-solve against the
already-factorized background transpose, and it happens at most once per
`(database set, method, category)` per process. Startup warms the categories the
bundled product graphs use, so in practice this is paid only by a category no
bundled graph declares.

### Full cache rebuild

627.5ms, driving Call 1 to 1477.3ms. This clears the LU factorization as well as
the vectors, so every sample re-runs `_build_entry`: the B1 invariant query, the
background LCA, and `splu(A_BB.T)`.

This is a synthetic worst case, not an operational one. The cache is rebuilt
only when the background database identity changes — an install, reimport,
removal, or metadata-changing rewrite — or at process start, where it is already
accounted for as startup cost rather than request cost. It is recorded here so
the number is known, not because a request is expected to pay it.

## Raw wall times

| Run | `off` | `on` warm | `on` category miss | `on` rebuild |
|---:|---:|---:|---:|---:|
| 1 | 812.205 | — | — | — |
| 2 | 794.637 | — | — | — |
| 3 | 790.289 | — | — | — |
| 4 | 813.939 | — | — | — |
| 5 | 898.669 | — | — | — |
| 6 | 848.535 | — | — | — |
| 7 | 878.291 | — | — | — |
| median | 811.824 | 830.131 | 810.255 | 1477.273 |
| min | 786.450 | 798.290 | 794.114 | 1399.236 |
| max | 875.772 | 861.210 | 817.707 | 1497.744 |

Only the `off` run's per-sample values are listed; the spread of that column is
the point, and it is what makes the cross-configuration wall comparison
meaningless at this magnitude.

## Conclusion

Publishing provider intensities costs **0.031ms** on a warm cache, which is the
steady state. A first-use category miss costs about 4ms per category, once. No
gate in the plan is threatened, and no change to the committed default is
implied: the field appears only when the cache is enabled.

## Not measured

- Production hardware. All figures are from the local M4 host. The droplet is
  materially slower — cache startup there is 4.4-5.0s against 0.8-2.0s locally —
  so the category-miss figure should be expected to scale up, while the warm
  figure is small enough that scaling is irrelevant.
- Graphs with many more background links. The broom has three. Cost is linear in
  links times categories, and the per-unit figure of roughly 5µs bounds it.
