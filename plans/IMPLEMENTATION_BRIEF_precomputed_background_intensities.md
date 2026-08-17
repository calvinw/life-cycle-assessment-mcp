# Implementation Brief: Precomputed Background Cumulative Intensities

Audience: coding agent working in `life-cycle-assessment-mcp`  
Design: [`PLAN_precomputed_background_intensities.md`](PLAN_precomputed_background_intensities.md)  
Date: August 17, 2026

## Objective

Verify empirically that the background half of the adjoint vector is independent
of request foreground structure, then implement Tier 1 behind a default-off
flag. Do not begin Tier 2 or Tier 3.

## Ground rules

- Test before optimizing. A failed phase is evidence and a stop condition.
- Keep the cached path differential until the comparison gate is reviewed.
- Do not refactor or clean up unrelated engine code.
- Report discrepancies with actual values; do not widen tolerances silently.
- Ask before expanding touched areas beyond `lca_core/`, `tests/`, `benchmarks/`,
  and `plans/`.

Two reviewed deviations are part of this brief:

1. Structural invariance is established by B1 plus bitwise-identical `A_BB` and
   `d_B`; independent full-system `y_B` vectors are not required to be bitwise
   identical because SuperLU permutations vary with foreground sparsity.
2. Differential numerical checks use the shipped explicit policy
   `rtol=1e-8, atol=1e-12`. The original stricter failures remain documented.

## Phase 0 — reconnaissance

Change no production code. Report, with paths and lines:

1. temporary foreground database creation, unique naming, and deletion;
2. `bc.LCA(...)` construction and actual `lci()` factorization behavior;
3. activity/product/biosphere index maps and reversed lookup rules;
4. the exact foreground/background discrimination rule;
5. whether the adjoint is shipped or only planned;
6. `ensure_ready()` behavior and reusable process caches;
7. calculation/startup locks and cache concurrency requirements;
8. reusable mock-background test setup; and
9. installed mock and BAFU matrix sizes and version metadata.

Deliverable: [`RECON_background_intensities.md`](RECON_background_intensities.md).

## Phase 1 — characterize current behavior

### Golden scores

For every YAML in `case_studies/`, `mock_examples/`, and the located
`bafu_examples/` set, record every configured category from `engine.run()` in
`tests/fixtures/golden_scores.json`. Regeneration requires an explicit
`--update-goldens`; assertions use `rtol=1e-12`.

### Timing baseline

Measure temporary foreground lifecycle, `lca.lci()`, per-category LCIA, request
transpose factorization, and Call 2 traversal. Record machine/environment and
absolute milliseconds in `benchmarks/baseline_pre_optimization.md`.

Gate: goldens and instrumentation pass with the production cache mode off.

## Phase 2 — decisive experiment

### B1

For every BAFU-linked and mock-linked fixture, partition matrix rows through
`lca.dicts.product` and columns through `lca.dicts.activity`:

```python
A_FB = A[fg_product_rows, :][:, bg_activity_cols]
assert A_FB.nnz == 0
assert A_BF.nnz > 0
```

The second assertion proves the partition is non-vacuous.

### Background-system invariance

Compare the BAFU broom and BAFU polyester T-shirt under one common method. Key
products and activities by Brightway node ID, reindex canonically, and assert
that `A_BB` and `d_B` are bitwise identical. Also compare full `y_B` between the
broom and a test-local two-process version with the same providers.

### Score decomposition

For every fixture/category, compute a background-only `y_B` and verify:

```python
score_decomposed = d_F @ s_F + D_B @ y_B
score_reference = lca.score
```

Use the reviewed `rtol=1e-8, atol=1e-12` policy. Record stricter diagnostic
failures rather than deleting them.

Gate: B1, structural invariance, and all score decompositions pass. Findings go
to `benchmarks/phase2_yb_invariance.md`.

## Phase 3 — Tier 1 behind a flag

### Cache

Implement a process-resident module that:

- factorizes `A_BB.T` once per background database identity;
- memoizes `y_B` by method/category;
- exposes immutable lookup by Brightway product node ID;
- keys on database names, dependency closure, project, and all available
  version/freshness metadata; and
- invalidates by publishing a new identity entry, never by product graph.

### Differential modes

```text
LCA_BACKGROUND_INTENSITY_CACHE=off|compare|on
```

- `off`: existing behavior; default.
- `compare`: compute both vectors, validate relative vector norm and final score,
  return the existing vector, and warn with actual values on disagreement.
- `on`: use cached intensities only after score reconciliation; disable and fall
  back on any invariant or numerical failure.

### Startup

Warm categories used by bundled product graphs, memoizing all others on first
use. Stop for review if cache startup exceeds approximately five seconds on
BAFU.

### Production B1 guard

At startup, query the freshness-validated indexed exchange projection for any
background output referencing the request foreground namespace. On every cached
request, assert the actual `A_FB` matrix block is empty. Name offenders, disable
the cache, and use the existing path on failure.

Gate: full suite passes in compare mode with no background-cache WARNING lines.

## Phase 4 — measure

Repeat the Phase 1 workload with mode `on`, cache prewarmed. Report absolute
milliseconds for the removed factorization, cache assembly, traversal, and total
Call 2 wall time. Do not claim a percentage without the absolute change.

Deliverable: `benchmarks/tier1_after_optimization.md`.

## Phase 5 — Tier 2

Do not start without explicit instruction. Returning provider/category
intensities changes both API and frontend contracts.

## Out of scope

- Tier 3 or any score-only foreground bypass;
- `result_id` caching;
- search projection behavior other than the read-only invariant query;
- SVG/frontend changes; and
- dependency upgrades.

## Stop conditions

Stop and report if goldens fail, B1 is vacuous or violated, structural systems
differ, decomposition fails the reviewed policy, compare mode warns, startup
exceeds five seconds, or implementation requires an unapproved scope expansion.

## Definition of done

- [x] Reconnaissance written and reviewed
- [x] Golden scores checked in and green
- [x] Baseline timings recorded
- [x] B1 asserted non-vacuously
- [x] Background-system invariance demonstrated
- [x] Score decomposition verified across all configured categories
- [x] Cache keyed, memoized, and product-node-ID based
- [x] Compare mode green across the full suite
- [x] Startup guard and fallback implemented
- [x] Post-optimization absolute timings recorded
- [x] Default remains `off`
- [ ] Tier 2 started only on explicit instruction
