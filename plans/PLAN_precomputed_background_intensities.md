# Plan: Precomputed Background Cumulative Intensities

Status: Tier 1 implemented behind a default-off flag and measured on the
feasibility branch  
Date: August 17, 2026  
Related plan: [`explanation-of-lazy-plan.md`](explanation-of-lazy-plan.md)

Plain-English overview with slider examples:
[`explainer_precomputed_background_intensities.md`](explainer_precomputed_background_intensities.md)

## Goal

Move the background portion of the per-request adjoint calculation out of the
interactive two-call pipeline. For a fixed background database set and LCIA
category, precompute the cumulative intensity of every background product once,
then reuse it for every product graph.

The existing lazy path solves

```text
A.T y = d, where d = B.T c
```

for every request and category. The background slice, `y_B`, contains no
foreground coefficients and can be cached without approximation.

## Structural invariant

Order technosphere product rows as foreground then background and activity
columns in the same scope order:

```text
A = ( A_FF  A_FB )
    ( A_BF  A_BB )
```

The required invariant is:

> **B1:** `A_FB = 0`; no background activity has an exchange referencing a
> request-created foreground product.

Background databases are installed before requests. Each request creates a
uniquely named temporary foreground database, writes only foreground exchanges,
and removes it in a `finally` block. Nothing in that lifecycle mutates a
background activity.

With B1, the transposed system is block upper-triangular:

```text
A.T = ( A_FF.T  A_BF.T )
      (   0     A_BB.T )
```

Therefore:

```text
A_BB.T y_B = d_B
y_F = A_FF^-T (d_F - A_BF.T y_B)
```

`A_BB` and `d_B = B_B.T c` depend only on the background database set and LCIA
method/category. The foreground depends on the background; the background does
not depend on the foreground.

## Score decomposition

For foreground demand `f = [f_F; 0]`, let
`s_F = A_FF^-1 f_F` and `D_B = -A_BF s_F`. Then:

```text
score = d_F.T s_F + D_B.T y_B
```

The second term is identical to the primal background contribution because:

```text
s_B = A_BB^-1 D_B
d_B.T s_B = (A_BB^-T d_B).T D_B = y_B.T D_B
```

Foreground and background loops, coproducts, substitution, and negative
background coefficients remain exact linear algebra. Product and activity
matrix index spaces must remain distinct.

For the single-process BAFU plastic broom, the climate score is the sum of three
background input amounts multiplied by their cached product intensities. There
is no direct foreground biosphere term.

## Delivery tiers

### Tier 1 — cache `y_B`

At startup, factorize `A_BB.T` once per background database set and populate
`y_B` for categories used by bundled examples. Memoize other categories on first
use. Call 2 then reconstructs the tiny foreground slice by back-substitution and
passes the complete cumulative vector to the existing traversal.

This is a relocation of the existing adjoint work. It removes the request
transpose factorization and makes the marginal category cost a cached solve or
lookup.

Implemented modes:

```text
LCA_BACKGROUND_INTENSITY_CACHE=off|compare|on
```

- `off`: unchanged shipped behavior; default.
- `compare`: compute cached and existing vectors, validate them, and return the
  existing result.
- `on`: use the cached vector, with score reconciliation and safe fallback.

### Tier 2 — return relevant intensities from Call 1

Attach the cached intensity for every resolved provider/category to the Call 1
response. The editor can then update totals locally for amount, functional-unit,
and provider changes. Payload cost is one float per link/category.

This changes the API contract and frontend. It begins only on explicit
instruction.

### Tier 3 — score without a foreground Brightway database

Resolve YAML providers, assemble tiny `A_FF` and `B_F` matrices directly, solve
`A_FF s_F = f_F`, and evaluate the decomposition. This could remove the fixed
temporary-database cost from score-only editing.

Tier 3 creates a second calculation route and is explicitly out of scope until
Tiers 1 and 2 have been measured. The real foreground database is still needed
for the aggregated LCI, direct-contribution table, and physical Sankey in the
current architecture.

## Cache identity and invalidation

The logical intensity key is:

```text
(background database identity, method, category)
```

Database identity includes the selected database names, their dependency
closure, project, and available version/content metadata. `mock_background`
provides a schema version and source SHA-256. The installed BAFU database does
not provide a durable source version or checksum, so the implementation records
and keys on all available freshness metadata (`number`, `modified`, `processed`,
backend, and dependencies) instead of silently keying on name alone. Adding a
durable BAFU source checksum remains desirable.

Recomputed identity automatically invalidates an entry after install, reimport,
removal, or metadata-changing rewrite. Product graph changes never invalidate
background intensities.

## Failure boundaries

The cache is invalid if any of the following occurs:

1. a background technosphere exchange references a foreground node;
2. foreground activities are written into a background database;
3. request-time scenario logic mutates background exchanges without becoming
   part of the cache identity;
4. characterization is nonlinear or demand-dependent; or
5. `A_BB` is rectangular or singular.

Startup checks the persisted exchange invariant using the freshness-validated,
indexed search projection. Every cached request independently asserts
`A_FB.nnz == 0` in the assembled matrix. A violation disables the cache and
falls back to the existing path; the engine never continues with an invalid
cache.

## Numerical policy

The mathematical background system was confirmed bitwise identical between
different BAFU foreground graphs. Independent full-system SuperLU solves can
nevertheless select different sparse permutations and produce parts-per-billion
differences on an ill-scaled system.

The reviewed policy is the existing production reconciliation tolerance:

```text
rtol = 1e-8
atol = 1e-12
```

Compare mode checks both the relative norm of the complete cached/reference
vectors and the reconstructed final score. It returns the reference vector.
On mode checks the cached final score before traversal. The original stricter
failures and solver diagnostics remain recorded in
[`../benchmarks/phase2_yb_invariance.md`](../benchmarks/phase2_yb_invariance.md).

## Validation and measurements

- B1 passed non-vacuously on all four BAFU-linked and three mock-linked fixtures.
- `A_BB` and `d_B` were bitwise identical across structurally different BAFU
  requests.
- The score decomposition passed all 20 configured categories under the reviewed
  numerical policy.
- Default-off and compare suites each passed 75 tests.
- Compare mode emitted no background-intensity discrepancy warnings.
- Startup populated six database/category combinations in 2.191 seconds, below
  the five-second gate.
- On the same host as the baseline, median BAFU Call 2 time fell from 891.390ms
  to 756.442ms, an absolute reduction of 134.948ms (15.1%).

See:

- [`RECON_background_intensities.md`](RECON_background_intensities.md)
- [`../benchmarks/baseline_pre_optimization.md`](../benchmarks/baseline_pre_optimization.md)
- [`../benchmarks/phase2_yb_invariance.md`](../benchmarks/phase2_yb_invariance.md)
- [`../benchmarks/tier1_startup_stop.md`](../benchmarks/tier1_startup_stop.md)
- [`../benchmarks/tier1_after_optimization.md`](../benchmarks/tier1_after_optimization.md)

## Current decision

Tier 1 is feasible and implemented behind the flag. The committed default must
remain `off`. Tier 2 and Tier 3 are not started by this plan.
