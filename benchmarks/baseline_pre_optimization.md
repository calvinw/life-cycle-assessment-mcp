# Baseline: Precomputed Background Cumulative Intensities

Status: Phase 1 pre-optimization baseline  
Date: August 17, 2026  
Branch: `plan/background-intensity-feasibility`  
Baseline commit: `aade58d`  
Workload: `bafu_examples/plastic_broom.yaml`

## Environment

- Host: local macOS 26.5.1, not a Codespace
- Architecture: arm64, Apple M4
- Memory: 16 GiB
- Python: 3.14.1
- brightway25: 1.1.1
- bw2calc: 2.5.0
- bw2data: 4.7
- bw-graph-tools: 0.9
- NumPy: 2.4.6
- SciPy: 1.18.0
- Sparse solver: SciPy/SuperLU; scikit-umfpack is not installed

Numbers in this document are meaningful only relative to measurements repeated
on this same host and software environment.

## Method

The configured Brightway project and database projection were warmed with one
unrecorded base-plus-Call-2 pair. Seven subsequent pairs were measured in the
same process.

The base call used `_run_analysis(..., include_contribution_graphs=False)` and
the contribution call used `_run_contribution_analysis(...)` for both categories
configured by the BAFU broom. Existing `performance_phases` instrumentation was
used without changing production code. An outer `time.perf_counter()` measured
wall time.

The phase named `lci_factorization` measures the shipped `lca.lci()` forward
solve. The code intentionally does not pass `factorize=True`. Foreground timing
includes both temporary database creation and cleanup because the existing
instrumentation accumulates both under `temporary_foreground_creation`.

## Results

All values are milliseconds.

### Base call

| Phase | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Wall time | 841.074 | 816.402 | 924.969 |
| Foreground create and cleanup | 345.206 | 342.084 | 427.147 |
| LCA construction | 25.080 | 24.676 | 32.376 |
| Forward `lca.lci()` solve | 167.740 | 162.717 | 178.502 |
| LCIA plus direct contributions, two categories | 176.028 | 173.257 | 189.232 |

### Call 2 contribution graphs

| Phase | Median | Minimum | Maximum |
|---|---:|---:|---:|
| Wall time | 891.390 | 857.147 | 1,212.500 |
| Foreground create and cleanup | 374.332 | 341.431 | 642.813 |
| LCA construction | 26.217 | 24.912 | 37.213 |
| Forward `lca.lci()` solve | 166.524 | 162.644 | 228.027 |
| Adjoint transpose factorization | 128.547 | 125.222 | 130.851 |
| LCIA, two categories | 2.230 | 2.016 | 2.806 |
| Contribution traversal, two categories | 92.117 | 86.059 | 99.956 |

The contribution-traversal phase includes the per-category adjoint back-solve
inside `_seed_adjoint_scores()` as well as graph traversal. Existing
instrumentation does not split these two operations.

## Raw wall and target-phase measurements

| Run | Base wall | Base foreground | Base forward solve | Call 2 wall | Call 2 foreground | Call 2 forward solve | Transpose factorization | Traversal |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 823.391 | 342.991 | 162.717 | 883.137 | 376.560 | 162.925 | 125.222 | 88.268 |
| 2 | 816.402 | 342.084 | 163.011 | 910.399 | 418.051 | 162.644 | 126.159 | 86.059 |
| 3 | 820.116 | 345.206 | 163.461 | 881.428 | 360.337 | 167.174 | 129.394 | 92.117 |
| 4 | 907.790 | 427.147 | 168.330 | 1,212.500 | 642.813 | 174.101 | 130.851 | 98.191 |
| 5 | 924.969 | 382.994 | 178.502 | 891.390 | 374.332 | 165.544 | 126.371 | 86.328 |
| 6 | 841.074 | 342.812 | 167.740 | 927.590 | 346.982 | 228.027 | 129.678 | 99.956 |
| 7 | 883.428 | 376.271 | 174.411 | 857.147 | 341.431 | 166.524 | 128.547 | 94.396 |

## Interpretation

The transpose factorization alone accounts for 128.547 ms, or about 14.4% of
median Call 2 wall time. Tier 1 can also remove the background portion of the
per-category adjoint back-solves currently included in the 92.117 ms traversal
phase, so 14.4% is a lower bound on the directly targeted request-time work, not
a prediction of end-to-end improvement.

Foreground creation and cleanup remains the largest measured Call 2 phase at
374.332 ms. The approximately 2.5 second foreground cost cited in the design
document did not reproduce on this warm local Apple M4 environment. It may still
describe Codespace or cold-volume behavior and should not be replaced by this
number outside this machine-specific comparison.

The traversal emitted its existing coverage warnings at the default cutoff for
the two requested categories. This benchmark records performance, not a change
to traversal coverage or cutoff behavior.
