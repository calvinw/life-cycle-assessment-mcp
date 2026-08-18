# Tier 1: Precomputed Background Cumulative Intensities

Status: Phase 4 measured; default remains off  
Date: August 17, 2026  
Branch: `plan/background-intensity-feasibility`  
Baseline commit: `aade58d`  
Workload: `bafu_examples/plastic_broom.yaml`

## Validation gate

Tier 1 was enabled only after the differential path passed the full suite:

```text
LCA_BACKGROUND_INTENSITY_CACHE=compare
Ran 75 tests in 42.701s
OK
```

Compare mode produced no background-intensity discrepancy warnings. It computed
both cumulative-intensity vectors, checked their relative vector norm and final
score with the approved `rtol=1e-8, atol=1e-12` numerical policy, and returned
the existing per-request Brightway result.

The BAFU T-shirt diagnostic that originally failed elementwise comparison had a
full-vector relative difference below `5e-10`. Both the cached and reference
solutions had relative algebraic residuals near `1e-13`. The largest absolute
entry differences were attached to cumulative intensities of millions or
billions and were parts-per-billion relative differences.

## Startup

With `compare`, startup populated six `(database set, method, category)` vectors
across `bafu` and `mock_background`:

```text
[lca_engine] Background intensity cache ready —
6 database/category combinations in 2.191s.
```

This remains below the implementation brief's approximately five-second gate.
The first rejected B1 implementation and the approved indexed replacement are
documented in `benchmarks/tier1_startup_stop.md`.

## Benchmark method

The environment and seven-sample method match
`benchmarks/baseline_pre_optimization.md`. This is the same local Apple M4 host,
Python environment, BAFU broom, two configured categories, one unrecorded warm-up
pair, and seven recorded base-plus-Call-2 pairs in one process.

The cache was populated before the warm-up. `LCA_BACKGROUND_INTENSITY_CACHE=on`
was used for the recorded calls. Existing phase instrumentation and an outer
`time.perf_counter()` provided the measurements.

All values below are milliseconds.

## Result

### Call 2 contribution graphs

| Phase | Before median | Tier 1 median | Absolute change |
|---|---:|---:|---:|
| Wall time | 891.390 | 756.442 | -134.948 |
| Foreground create and cleanup | 374.332 | 365.921 | -8.411 |
| LCA construction | 26.217 | 25.892 | -0.325 |
| Forward `lca.lci()` solve | 166.524 | 164.206 | -2.318 |
| Request adjoint transpose factorization | 128.547 | 0 | -128.547 |
| Cached-vector assembly, two categories | 0 | 12.037 | +12.037 |
| LCIA, two categories | 2.230 | 2.054 | -0.176 |
| Contribution traversal, two categories | 92.117 | 87.555 | -4.562 |

Median Call 2 wall time fell by `134.948ms`, from `891.390ms` to
`756.442ms` on this machine. That is a 15.1% reduction, reported only alongside
the absolute values because request timings vary with temporary foreground I/O.

The directly targeted phases show the expected mechanism: the `128.547ms`
request transpose factorization disappeared, while reconstructing the request
vector from cached `y_B` added `12.037ms` for two categories. Traversal was also
`4.562ms` lower because it no longer performed the background back-solves.

### Tier 1 distribution

| Phase | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Call 2 wall time | 756.442 | 748.613 | 996.116 |
| Foreground create and cleanup | 365.921 | 354.847 | 603.732 |
| LCA construction | 25.892 | 24.431 | 26.327 |
| Forward `lca.lci()` solve | 164.206 | 164.122 | 164.801 |
| Cached-vector assembly, two categories | 12.037 | 11.876 | 12.257 |
| LCIA, two categories | 2.054 | 1.990 | 2.148 |
| Contribution traversal, two categories | 87.555 | 85.484 | 88.088 |

The transpose-factorization phase was absent from all seven Tier 1 samples.

### Raw measurements

| Run | Call 2 wall | Foreground | Forward solve | Cache assembly | Traversal |
|---:|---:|---:|---:|---:|---:|
| 1 | 996.116 | 603.732 | 164.644 | 12.205 | 87.555 |
| 2 | 748.613 | 354.847 | 164.186 | 12.037 | 87.924 |
| 3 | 770.575 | 373.798 | 164.199 | 12.257 | 87.773 |
| 4 | 768.096 | 376.067 | 164.801 | 11.946 | 88.088 |
| 5 | 756.442 | 365.921 | 164.206 | 11.876 | 86.932 |
| 6 | 755.618 | 364.615 | 164.223 | 12.137 | 85.484 |
| 7 | 749.590 | 355.619 | 164.122 | 11.969 | 86.564 |

## Interpretation

Tier 1 produces a visible but bounded improvement. The median savings closely
track the removed transpose factorization, so the measurement supports the
implementation rather than suggesting a larger architectural effect.

Temporary foreground creation and the forward solve still consume about
`530ms` at their medians. Tier 1 does not remove either operation. This confirms
the design document's expectation that eliminating the foreground build would
require the separately gated Tier 3 architecture; Tier 3 remains out of scope.

The default remains `off`. Phase 5/Tier 2 has not been started.
