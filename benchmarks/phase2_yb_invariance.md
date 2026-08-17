# Phase 2: Background-Intensity Invariance Experiment

Status: Phase 2 accepted with documented numerical policy  
Date: August 17, 2026  
Branch: `plan/background-intensity-feasibility`  
Baseline commit: `aade58d`

## Outcome

Invariant B1 passed directly and non-vacuously on every linked fixture. The
strict empirical `y_B` comparison then failed for two BAFU graphs with different
provider sets. After review approved the structural-invariance criterion, Task
2.3 was run. Eighteen of 20 scores passed a strict mixed tolerance of
`rtol=1e-10, atol=1e-12`; both BAFU T-shirt categories failed. No tolerance was
widened and no production code was changed.

Read-only diagnostics show that the two runs have bitwise-identical `A_BB` and
`d_B`. Their full-system SuperLU permutations differ, and the resulting numerical
solutions differ above `rtol=1e-12`. This distinguishes a numerical
factorization-path effect from foreground-dependent background coefficients, but
it does not satisfy the implementation brief's stated acceptance test.

## Task 2.1: Invariant B1

The test independently mapped product rows through `lca.dicts.product` and
activity columns through `lca.dicts.activity`. Foreground products were selected
from the request database; foreground activities were selected by the same
explicit node-ID membership rule used by production contribution code.

| Fixture | Matrix | `A_FB.nnz` | `A_BF.nnz` |
|---|---:|---:|---:|
| `bafu_examples/cotton_fiber_bafu.yaml` | 11,948 x 11,948 | 0 | 1 |
| `bafu_examples/plastic_broom.yaml` | 11,948 x 11,948 | 0 | 3 |
| `bafu_examples/polyester_tshirt_bafu.yaml` | 11,948 x 11,948 | 0 | 2 |
| `bafu_examples/wool_yarn_bafu.yaml` | 11,948 x 11,948 | 0 | 1 |
| `mock_examples/mock_plastic_broom.yaml` | 5 x 5 | 0 | 2 |
| `mock_examples/mock_plastic_broom_simple.yaml` | 5 x 5 | 0 | 2 |
| `mock_examples/mock_storage_bin.yaml` | 5 x 5 | 0 | 1 |

All seven cases passed. Each `A_BF` block was non-empty, proving that the
partition did not pass vacuously.

Test: `tests/test_invariant_b1.py`.

## Task 2.2: `y_B` invariance

The selected common method was:

```text
EF v3.1 | climate change | global warming potential (GWP100)
```

Each full adjoint was solved independently with
`splu(A.T.tocsc()).solve(d)`. Background entries were keyed by Brightway product
node ID from `lca.dicts.product.reversed`, never by matrix index.

### Existing different-provider fixtures

Compared:

- `bafu_examples/plastic_broom.yaml`; and
- `bafu_examples/polyester_tshirt_bafu.yaml`.

Both exposed exactly the same 11,947 background product IDs. The assertion at
`rtol=1e-12, atol=0` failed:

- entries passing: 459 of 11,947;
- entries failing: 11,488 of 11,947;
- bitwise-equal entries: 275;
- maximum absolute difference: `3.3913021087646484`;
- NumPy's assertion reported maximum relative difference: `3.61420357`.

A subsequent explicit ratio diagnostic found expected-zero entries with nonzero
round-off in the other solve, for which relative error is unbounded at
`atol=0`. This is one reason a pure relative vector comparison is especially
strict here; the tolerance was nevertheless left unchanged as required.

The largest absolute difference occurred at BAFU product node
`329389991365713923`, code `562673`, “Production plant, natural gas”:

| Solve | `y_B` |
|---|---:|
| Broom full system | `8752195947.756193` |
| T-shirt full system | `8752195944.364891` |
| Background-only system | `8752195947.756193` |

The absolute difference is `3.3913021087646484`; relative to the T-shirt value it
is about `3.87e-10`.

For context only, without changing the acceptance criterion:

| Comparison tolerance, `atol=0` | Entries passing |
|---|---:|
| `rtol=1e-12` | 459 / 11,947 |
| `rtol=1e-10` | 6,161 / 11,947 |
| `rtol=1e-8` | 11,907 / 11,947 |

### Different foreground process counts

The BAFU broom was also compared with a test-local two-process version using the
same three BAFU providers behind an added foreground intermediate. This stronger
matrix-offset/process-count comparison passed at `rtol=1e-12, atol=0`.

This result does not cancel the different-provider failure; it helps localize
the factorization sensitivity to changes in the full system's sparsity pattern.

Test: `tests/test_yb_invariance.py`.

## Diagnostic evidence

The two failing full systems were reindexed into canonical background product and
activity node-ID order before comparison.

| Diagnostic | Result |
|---|---:|
| Background product ID sets equal | yes |
| Background activity ID sets equal | yes |
| `(A_BB,broom - A_BB,shirt).nnz` | 0 |
| Maximum `A_BB` coefficient difference | 0 |
| `d_B` bitwise equal | yes |
| Maximum `d_B` difference | 0 |
| Full-LU row-permutation positions differing | 1,270 |
| Full-LU column-permutation positions differing | 1,270 |
| Broom background-equation max residual | `5.07516158432253e-7` |
| T-shirt background-equation max residual | `5.061096377545482e-7` |

The background-only solve and broom full-system solve were bitwise equal on all
11,947 entries. The T-shirt full-system solve differed from both with the same
statistics as the full-vs-full comparison.

The evidence supports this interpretation:

1. The mathematical background system is identical: both `A_BB` and `d_B` are
   bitwise equal.
2. B1 holds, so no foreground coefficient enters the background equation.
3. Different foreground provider links change the full sparse matrix pattern.
4. SuperLU chooses different permutations in 1,270 positions.
5. The ill-scaled full-system solves therefore reach numerically different
   approximations to the same exact `y_B`.

This preserves the algebraic rationale for a standalone background solve, but
refutes the stronger design statement that independently factorized full-system
background slices will be bitwise identical or agree at `rtol=1e-12` in this
installed BAFU system.

## Initial stop decision

Per the implementation brief:

- Task 2.3 score decomposition had not yet been run;
- no expected-failure marker was added;
- no tolerance was loosened;
- the failing test remains a normal failing assertion; and
- no cache or production fallback was implemented.

Review is required before choosing whether to:

1. keep the original empirical criterion and halt the proposal; or
2. explicitly revise the experiment to treat bitwise-equal `A_BB` and `d_B` as
   the structural invariance proof, then separately test the background-only
   decomposition against `lca.score` at the already specified `rtol=1e-10`.

Option 2 would be a reviewed change to the brief, not an automatic workaround.

## Review decision

Review approved option 2: retain the full-adjoint mismatch as a documented
numerical finding, accept bitwise-equal `A_BB` and `d_B` as the structural
invariance check, and proceed to the background-only score decomposition at
`rtol=1e-10`.

## Task 2.3: Score decomposition

For every spec and configured category, the experiment computed a background-only
intensity vector with no foreground database present, then evaluated:

```text
score_decomposed = d_F @ s_F + D_B @ y_B_background_only
score_reference  = lca.score
```

The implemented check used `rtol=1e-10, atol=1e-12`. Results:

- total categories: 20;
- passing: 18;
- failing: 2;
- all foreground-only and mock-background categories passed;
- six of eight BAFU categories passed; and
- both categories in `bafu_examples/polyester_tshirt_bafu.yaml` failed.

The failures were:

| Category | Reference | Decomposed | Absolute error | Relative error |
|---|---:|---:|---:|---:|
| Acidification | `0.002807449526233412` | `0.0028074495306178683` | `4.384456339656673e-12` | `1.561722231757818e-9` |
| Climate change | `2.283358705543972` | `2.2833587064176766` | `8.73704664172692e-10` | `3.826401266044384e-10` |

The other BAFU relative errors ranged from about `3.53e-12` to `4.37e-11` and
passed the strict check. Foreground-only and mock scores were exact except for
one foreground-only difference of `8.88e-16`.

This pattern is consistent with the Task 2.2 numerical finding. The same T-shirt
full-system factorization whose `y_B` differed from the background-only solve is
the only graph whose final decomposed scores fail. The broad exact agreement on
foreground-only and mock cases, correct signs on all cases, and small errors on
the remaining BAFU cases argue against a sign, scaling, or index-space bug.

### Absolute-tolerance ambiguity in the written brief

The brief's example assertion is:

```python
np.isclose(score_decomposed, score_reference, rtol=1e-10)
```

NumPy supplies `atol=1e-8` when it is omitted. Under that literal assertion, all
20 categories pass because both absolute errors are below `1e-8`.

The experiment instead specified `atol=1e-12` explicitly so that the absolute
tolerance would not silently dominate the requested relative tolerance. Under
that stricter interpretation, the two results above fail. The test remains
failing pending an explicit decision; it was not changed to NumPy's default
absolute tolerance after observing the results.

## Current stop decision

The proposal cannot satisfy a predominantly relative `rtol=1e-10` comparison
against every existing full-system Brightway score on this BAFU installation.
The discrepancies are tiny in practical terms but above the strict threshold.

Review must now choose among:

1. halt Tier 1 under the strict mixed tolerance;
2. approve the literal written `np.isclose(..., rtol=1e-10)` criterion, including
   its default `atol=1e-8`; or
3. define and justify a different explicit numerical error policy before any
   production cache work begins.

## Final numerical-policy decision

Review approved option 3 using the policy already enforced by the shipped
adjoint reconciliation guard:

```text
rtol = 1e-8
atol = 1e-12
```

This avoids NumPy's comparatively large implicit `atol=1e-8`, retains a strict
near-zero absolute bound, and allows the measured SuperLU ordering variation.
All 20 decomposed scores pass this explicit policy. The original strict results
and the two `rtol=1e-10, atol=1e-12` failures remain recorded above; they were
not removed or reclassified.
