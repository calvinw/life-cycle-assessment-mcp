# Tier 1 Startup Stop Report

Status: Initial Phase 3.3 stop resolved; repeated startup gate passed  
Date: August 17, 2026  
Branch: `plan/background-intensity-feasibility`

## Result

With `LCA_BACKGROUND_INTENSITY_CACHE=compare`, `ensure_ready()` warmed six
database/category combinations across two database sets:

```text
[lca_engine] Background intensity cache ready —
6 database/category combinations in 13.889s.
```

Measured outer startup time was `14.161263s`. This exceeds the implementation
brief's approximately five-second stop threshold, so implementation and
compare-mode suite work halted.

The cache contained:

- two factorizations/database entries: `bafu` and `mock_background`;
- six memoized method/category vectors; and
- no disabled/fallback state.

## Cause isolation

The direct exchange-level production B1 guard was timed independently:

| Database set | Guard time |
|---|---:|
| `bafu` | `12.675353s` |
| `mock_background` | `0.002771s` |

The guard currently walks every background activity and technosphere exchange
through Brightway object proxies to name any exchange that targets a temporary
foreground database. This accounts for nearly all of the startup regression.

For comparison, the pre-optimization benchmark measured the full BAFU transpose
factorization itself at a median `128.547ms`. The cache's linear algebra is not
the source of the five-second gate failure.

## State at the initial stop

The branch currently contains uncommitted Tier 1 work:

- `lca_core/background_intensity.py` implements database identity, one transpose
  factorization per database set, method memoization, node-ID lookup, foreground
  back-substitution, and B1 guards;
- `lca_core/engine.py` implements default-off `off|compare|on` integration,
  startup warming, comparison, and safe fallback; and
- `lca_core/contribution_graph.py` can consume a supplied cumulative-intensity
  vector without solving the full adjoint again.

Default-off focused tests passed after these changes. At this point compare/on
behavior and the full suite had not been accepted because the startup stop
condition occurred first.

## Review choices

The likely safe change is to replace the object-by-object B1 scan with a matrix
or indexed-exchange query that checks the same invariant without materializing
every Brightway proxy. That would be a deliberate change to the Phase 3.4 guard
implementation after observing the stop, so it has not been done automatically.

Alternatives are:

1. approve a faster equivalent B1 guard and repeat the startup gate;
2. populate the cache lazily after startup, accepting first-use latency; or
3. halt Tier 1.

## Review decision

Review approved option 1: use an indexed query over the already
freshness-validated search projection for the startup exchange check, while
retaining the direct `A_FB.nnz == 0` matrix assertion on every cached request.
The startup gate must be repeated before compare/on validation continues.

## Repeated startup gate

After the approved guard change:

```text
[lca_engine] Background intensity cache ready —
6 database/category combinations in 2.016s.
```

Measured outer `ensure_ready()` time was `2.284248s`. The cache again contained
two database entries and six memoized method/category vectors, with no disabled
or fallback state.

The repeated cache warm-up is `11.873s` faster than the rejected implementation
and remains below the five-second gate. Phase 3 validation may continue.

## Subsequent Phase 3 gate

After continuing with the approved indexed guard, the full suite passed in
`compare` mode:

```text
Ran 75 tests in 42.701s
OK
```

The measured startup cache population in that suite was `2.191s`. No
background-intensity comparison or fallback warnings were logged. Phase 3 is
therefore accepted; post-optimization results are recorded in
`benchmarks/tier1_after_optimization.md`.
