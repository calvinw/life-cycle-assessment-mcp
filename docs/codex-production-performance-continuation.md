# Codex Continuation Guide: Production LCA Performance

This is the authoritative continuation brief for Codex running on the
DigitalOcean droplet that hosts the production LCA service.

Read this entire document before taking action. Continue from the existing
diagnostic checkout and preserve all uncommitted work. Do not restart, deploy,
commit, push, install software in the production container, or modify
production data unless the user explicitly approves that specific action.

## Mission

Find and fix the reason the production two-stage Plastic Broom LCA takes about
30–36 seconds while the same work takes about 6 seconds on the developer's
Mac. The user also observed faster behavior on another Linux workstation, so
do not assume that the difference is simply macOS versus Linux.

The immediate task is to finish, review, and validate the existing structured
phase-timing patch. After the user manually deploys an approved patch through
Coolify, collect phase timings from the production engine. Use those
measurements to recommend the smallest effective performance fix.

Correctness is currently good. Do not sacrifice result equality, contribution
graph correctness, or the lazy two-stage API behavior for speed.

## User's operating model

- The user manually deploys through Coolify.
- Codex may prepare and test code, but must not deploy or restart production.
- Codex must not commit or push unless the user explicitly says to do so.
- Prefer simple scripts when asking the user to run commands. Multiline shell
  fragments have pasted badly in the user's terminal.
- The user has a root terminal open on the droplet host.
- Codex normally runs as the unprivileged `codexdiag` account.
- Docker access is not required for editing or unit testing the diagnostic
  checkout.
- Membership in the `docker` group is effectively root access. Do not request
  it unless container access is necessary and the user understands that
  consequence.

## Locations and service identifiers

- Repository:
  `https://github.com/calvinw/life-cycle-assessment-mcp`
- Diagnostic checkout expected on the droplet:
  `/home/codexdiag/life-cycle-assessment-mcp`
- Production endpoint:
  `https://lca-mcp.mathplosion.com`
- Health endpoint:
  `https://lca-mcp.mathplosion.com/api/health`
- Test case:
  `bafu_examples/plastic_broom.yaml`
- Product editor repository on the developer's machine:
  `../product-editor-graph`

The LCA container observed during this investigation was:

```text
078f44cebcdf
lca-mcp-eoogg04soosgwk8c0wogs04g-001327149968
```

Container IDs change after deployments. Always resolve the current container
with `docker ps` instead of assuming that this ID is still valid.

## Repository and deployment history

Relevant repository commits:

```text
aa38a89 Add production performance investigation handoff
25881c7 Fix adjoint score reconciliation tolerance
c93996c Limit LCA to configured impact categories
331b8b3 Implement lazy two-call LCA analysis
```

Commit `25881c7` changed the contribution-graph adjoint score reconciliation
tolerance to:

```python
ADJOINT_SCORE_REL_TOLERANCE = 1e-8
ADJOINT_SCORE_ABS_TOLERANCE = 1e-12
```

That was a correctness fix, not a performance fix. The running container
printed an adjoint relative tolerance of `1e-08`, definitively confirming that
the fix reached production.

The diagnostic checkout was at `aa38a89` before the instrumentation work
started. Confirm the present state rather than assuming it:

```bash
cd /home/codexdiag/life-cycle-assessment-mcp
git status --short
git log -5 --oneline --decorate
```

Do not reset, restore, stash, clean, or otherwise discard changes. The current
uncommitted instrumentation patch belongs to this investigation.

## Correctness status

The two-stage production workflow succeeds:

1. `POST /api/lca/base`
2. `POST /api/lca/contribution` for:
   - `acidification | accumulated exceedance (AE)`
   - `climate change | global warming potential (GWP100)`

The contribution response previously contained:

| Category | Nodes | Edges | Flows | Coverage |
|---|---:|---:|---:|---:|
| Acidification | 73 | 72 | 40 | approximately 0.757 |
| Climate change | 85 | 84 | 39 | approximately 0.712 |

Both graphs can report `status: "partial"` because of the configured impact
cutoff. That is expected and is not an error.

The pre-deployment local fix passed 36 targeted tests, including the real BAFU
Plastic Broom regression.

## Timing evidence collected so far

An early production measurement after the correctness deployment was:

| Stage | Production | Developer Mac |
|---|---:|---:|
| Base | 20.53 s | 3.10 s |
| Contribution, two categories | 15.48 s | 2.87 s |
| Combined | 36.00 s | 5.97 s |

Three later sequential production pairs run from the droplet were:

| Run | Base | Contribution | Combined |
|---:|---:|---:|---:|
| 1 | 15.58 s | 15.22 s | 30.81 s |
| 2 | 16.56 s | 14.82 s | 31.39 s |
| 3 | 13.74 s | 15.29 s | 29.03 s |

There was no meaningful warm-up improvement.

All measured responses were correct and had identical scores and graph sizes.

Response sizes were approximately:

- Base: 724,648 bytes
- Contribution for two categories: 240,368 bytes

Production did not return a compression encoding. However, when the benchmark
was run from the droplet host, only about 2–4 milliseconds elapsed after the
first response byte. Nearly all of the 14–16 seconds per call occurred before
the first byte, so response transfer and missing compression do not explain
the observed server-side delay.

## Host and container evidence

The droplet is a DigitalOcean Basic shared-CPU instance:

- 4 `DO-Regular` vCPUs
- 8 GB RAM
- 60 GB disk
- x86-64/KVM
- one thread per core visible to the guest

Observed host load was low:

- Load average around `0.45, 0.38, 0.36`
- Approximately 5.8 GiB of 7.8 GiB RAM available
- Negligible swap usage
- No swap-in or swap-out during samples
- No meaningful memory pressure

During one 13.71-second base request, host-wide averages across the four
visible CPUs were approximately:

- user CPU: 34.3%
- system CPU: 3.0%
- idle: 62.5%
- I/O wait: 0.2%
- steal: 0.2%

This is consistent with CPU-heavy work using roughly one to one-and-a-half
cores on average, not work saturating all four cores.

The production container had no configured CPU or memory quota:

```text
NanoCpus=0
CpuQuota=0
CpuPeriod=0
CpuShares=0
CpusetCpus=
Memory=0
MemorySwap=0
```

Inside its cgroup:

```text
cpu.max: max 100000
cpuset.cpus.effective: 0-3
nr_throttled: 0
throttled_usec: 0
memory.max: max
memory.current: approximately 321 MB
memory.swap.max: max
nproc: 4
```

Docker resource limits, cgroup throttling, memory exhaustion, swapping, and
ordinary host load are therefore not supported by the current evidence as the
primary explanation. Shared-vCPU single-core performance or intermittent host
contention can still matter even without an explicit quota.

## Numerical environment evidence

The production container reports:

- Python 3.11.15
- NumPy 2.4.6
- x86-64 Linux
- x86-64-v2 baseline with x86-64-v3 SIMD found
- OpenBLAS 0.3.31
- OpenBLAS dynamic architecture, Haswell target available
- 64-bit integer OpenBLAS build
- standard SciPy `splu` from
  `scipy.sparse.linalg._dsolve.linsolve`

The lockfile selects SciPy 1.17.1 on Python 3.11. Capture the running SciPy
version directly if it has not yet been recorded, but do not install or change
it merely for inspection.

Optional solvers were absent:

```text
scikits.umfpack: False
pypardiso: False
sksparse: False
```

Brightway emitted its standard warning that `pypardiso` is not installed and
could speed calculations on x86-64.

`threadpoolctl` is not installed. NumPy therefore could not report the active
OpenBLAS thread count through `np.show_runtime()`. Do not modify the running
container merely to install this diagnostic package.

The faster developer Mac reports:

- Apple Silicon
- Python 3.14.1
- NumPy 2.4.6 using Apple Accelerate
- SciPy 1.18.0
- standard SciPy SuperLU
- no UMFPACK, Pardiso, or scikit-sparse

Therefore:

- Production does have an optimized numerical library.
- The slowdown is not explained by a completely unaccelerated NumPy build.
- Missing `pypardiso` remains a possible optimization, but it is not a complete
  explanation by itself because the faster Mac also lacks it.
- Sparse `splu`/SuperLU work may be largely single-threaded, making per-core
  CPU performance important.
- A separate Linux workstation was reportedly faster, so compare actual
  measured phases before attributing everything to architecture.

## Current instrumentation patch

A previous Codex turn prepared but did not commit the instrumentation patch.
Expected modified files:

```text
lca_core/engine.py
lca_server.py
tests/test_performance_instrumentation.py
```

Reported diff size:

```text
lca_core/engine.py                       +170 -12
lca_server.py                             +53  -6
tests/test_performance_instrumentation.py +114  -0
Total                                    +337 -18
```

The patch is intended to emit one engine timing record and one REST timing
record for each operation. It must never log YAML, request bodies, LCA results,
product graphs, database contents, environment variables, secrets, or
exception details.

Expected engine event:

```json
{
  "event": "lca_engine_performance",
  "operation": "base",
  "total_seconds": 12.345678,
  "phases": {
    "yaml_parsing_and_validation": 0.001234,
    "brightway_project_readiness": 0.000123,
    "temporary_foreground_creation": 1.234567,
    "lca_construction": 0.123456,
    "lci_factorization": 7.123456,
    "inventory_base_result_construction": 0.234567,
    "lcia_calculation_and_direct_contributions": {
      "total_seconds": 2.345678,
      "categories": [
        {
          "category": "climate change | global warming potential (GWP100)",
          "seconds": 1.234567
        }
      ]
    },
    "result_validation": 0.012345
  }
}
```

Contribution events additionally include:

```json
{
  "adjoint_transpose_factorization": 1.234567,
  "contribution_traversal_per_category": {
    "total_seconds": 2.345678,
    "categories": [
      {
        "category": "climate change | global warming potential (GWP100)",
        "seconds": 2.345678
      }
    ]
  }
}
```

The REST event is intended to be concise:

```json
{
  "event": "lca_rest_performance",
  "operation": "base",
  "total_seconds": 12.456789,
  "phases": {
    "json_response_serialization": 0.012345
  }
}
```

The reported logger uses an immediate-flushing `StreamHandler`.

The patch reports that it covers:

- identical instrumented and uninstrumented base results;
- expected engine phase names;
- adjoint and per-category contribution timings;
- unchanged serialized REST content;
- absence of sensitive request markers and `product_graph` from logs; and
- one engine or REST record per tested operation.

Already completed:

- `python3 -m compileall -q lca_core lca_server.py tests` passed.
- `git diff --check` passed.

Not yet completed at the time of this handoff:

- The focused instrumentation tests did not run because the diagnostic host
  checkout lacked NumPy and Brightway dependencies.
- `tests.test_lca_core_api` hit the same missing-dependency blocker.

No dependencies were installed by that Codex turn.

## Immediate continuation procedure

### Step 1: preserve and inspect the patch

From the diagnostic checkout:

```bash
cd /home/codexdiag/life-cycle-assessment-mcp
git status --short
git diff --stat
git diff --check
```

Read every changed section in:

- `lca_core/engine.py`
- `lca_server.py`
- `tests/test_performance_instrumentation.py`

Review for the following before running it:

1. `time.perf_counter()` or an equivalently monotonic high-resolution clock is
   used.
2. Timing does not change control flow, calculation order, solver selection,
   returned values, result IDs, or serialization.
3. Logger handlers are not duplicated when modules are imported or reloaded.
4. Timing logs go to normal container stdout/stderr and flush promptly.
5. Exactly one engine summary and one REST summary are emitted per successful
   operation.
6. Failure logging, if present, contains no input or exception details that
   could expose data.
7. Per-category timing is bounded by the requested category count; there are
   no per-node or per-edge messages.
8. No timing helper introduces mutable global request state.
9. Concurrent requests cannot mix timing dictionaries.
10. Tests do not depend on exact duration values or machine speed.
11. REST content is byte-for-byte or object-for-object equivalent, apart from
    normal nondeterministic fields that already existed.
12. The patch does not change the production log level globally.

The current phase boundaries are known not to isolate all work:

- foreground cleanup is combined with foreground creation;
- calculation-lock queue time appears only in total time;
- method lookup/configuration falls between coarse boundaries;
- base result construction combines inventory extraction, metadata, Sankey,
  and final assembly;
- REST request parsing is included only in the REST total; and
- network transfer remains client-measured.

These limitations are acceptable for the first diagnostic deployment if the
sum of named phases is close enough to total time to identify a dominant
phase. Do not expand the patch merely for completeness. If unexplained time is
large, add an explicit `unattributed_seconds` value or a calculation-lock wait
timer in a follow-up patch.

### Step 2: install dependencies only in the diagnostic environment

It is acceptable to install project dependencies into the `codexdiag`
checkout's `.venv`. This does not require Docker access and must not alter the
production container.

The root user may run `/root/test-instrumentation.sh` if it was created from
the earlier instructions, or Codex may run the equivalent commands as
`codexdiag`:

```bash
cd /home/codexdiag/life-cycle-assessment-mcp
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen --extra server
```

This installation must remain under `/home/codexdiag`. Do not use the live
container, production virtual environment, or Brightway volume.

### Step 3: validate the patch

Run at least:

```bash
uv run python -m unittest -v \
  tests.test_performance_instrumentation \
  tests.test_lca_core_api \
  tests.test_lca_results_extension
```

Also run:

```bash
uv run python -m compileall -q lca_core lca_server.py tests
git diff --check
```

If a test requires external LCA data that is unavailable, distinguish that
environmental blocker from an actual failure. Do not silently skip failures.
Run the largest safe subset that uses the repository's mock/test fixtures.

Report:

- exact command;
- pass, fail, error, and skip counts;
- full failing test names;
- the shortest useful failure explanation;
- whether result equality tests passed;
- whether sensitive-log exclusion tests passed; and
- whether logging count tests passed.

Do not commit, push, build, deploy, or restart after the tests. Return the
result to the user for approval.

### Step 4: prepare an approval-ready patch report

After successful validation, provide:

- `git status --short`
- `git diff --stat`
- a concise description of every production-code change;
- tests executed and their results;
- known instrumentation blind spots;
- expected production log event names; and
- the exact proposed commit message.

Suggested commit message:

```text
Add structured LCA phase timing diagnostics
```

Do not create the commit until explicitly authorized.

## Procedure after the user approves commit and push

Only after explicit approval:

1. Commit only the three instrumentation files.
2. Do not include unrelated work.
3. Push the approved branch or `main` exactly as directed.
4. Report the commit SHA.
5. Stop and let the user deploy manually through Coolify.

Do not trigger Coolify, call a deployment webhook, restart the current
container, or rebuild production yourself.

## Procedure after the user confirms manual deployment

### Confirm health and code version

Use the public health endpoint:

```bash
curl --silent --show-error --max-time 20 \
  -w '\nhttp=%{http_code} total=%{time_total}s\n' \
  https://lca-mcp.mathplosion.com/api/health
```

Resolve the new container:

```bash
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
```

Do not assume the old container ID remains current.

### Capture a bounded log window

Record a UTC start time immediately before the benchmark:

```bash
LCA_LOG_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

After resolving the current container, set:

```bash
LCA_CONTAINER_ID='<confirmed-current-id>'
```

Do not print the whole historical production log. After the benchmark, filter
only the two structured event names:

```bash
docker logs --since "$LCA_LOG_START" "$LCA_CONTAINER_ID" 2>&1 \
  | grep -E '"event": "(lca_engine_performance|lca_rest_performance)"'
```

If the Python logger prefixes timestamps or severity text, retain the prefix
but extract only matching timing lines.

### Run the exact sequential benchmark

Run from a clean repository checkout on the droplet host, not inside the
production container:

```bash
cd /home/codexdiag/life-cycle-assessment-mcp
```

Create a temporary output directory:

```bash
LCA_VERIFY_DIR="$(mktemp -d /tmp/lca-broom-timing.XXXXXX)"
```

Create the base request:

```bash
jq -Rs '{product_graph: .}' bafu_examples/plastic_broom.yaml \
  > "$LCA_VERIFY_DIR/base-request.json"
```

For each of three sequential runs:

1. POST the base request.
2. Verify HTTP 200.
3. Read `result_id` from that run's base response.
4. Build the contribution request with the two exact categories.
5. POST the contribution request.
6. Verify HTTP 200.
7. Record HTTP total and response size.
8. Do not overlap requests.

Base command template:

```bash
curl --silent --show-error --max-time 120 \
  -o "$LCA_VERIFY_DIR/base-response-RUN.json" \
  -w 'base run=RUN http=%{http_code} ttfb=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' \
  -H 'Content-Type: application/json' \
  --data-binary @"$LCA_VERIFY_DIR/base-request.json" \
  https://lca-mcp.mathplosion.com/api/lca/base
```

Build the matching contribution request:

```bash
LCA_RESULT_ID="$(jq -r '.result_id' "$LCA_VERIFY_DIR/base-response-RUN.json")"
jq -Rs --arg rid "$LCA_RESULT_ID" \
  '{
    product_graph: .,
    categories: [
      "acidification | accumulated exceedance (AE)",
      "climate change | global warming potential (GWP100)"
    ],
    result_id: $rid
  }' \
  bafu_examples/plastic_broom.yaml \
  > "$LCA_VERIFY_DIR/contribution-request-RUN.json"
```

Contribution command template:

```bash
curl --silent --show-error --max-time 120 \
  -o "$LCA_VERIFY_DIR/contribution-response-RUN.json" \
  -w 'contribution run=RUN http=%{http_code} ttfb=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' \
  -H 'Content-Type: application/json' \
  --data-binary @"$LCA_VERIFY_DIR/contribution-request-RUN.json" \
  https://lca-mcp.mathplosion.com/api/lca/contribution
```

Replace `RUN` with `1`, `2`, and `3`. A small temporary script is preferable
to asking the user to paste these commands repeatedly.

Validate correctness without printing complete response bodies:

```bash
jq '{
  detail,
  result_id,
  graphs: [
    (.contribution_graphs // [])[] |
    {
      label,
      status,
      total_score,
      coverage,
      nodes: (.nodes | length),
      edges: (.edges | length),
      flows: (.flows | length)
    }
  ]
}' "$LCA_VERIFY_DIR/contribution-response-1.json"
```

Delete temporary response files only if the user asks. Otherwise report their
location so they can be inspected.

### Correlate HTTP and engine timings

For every run, construct a table like:

| Run | Operation | HTTP total | Engine total | Dominant phase | Phase seconds | REST serialization | Unattributed |
|---:|---|---:|---:|---|---:|---:|---:|
| 1 | base | | | | | | |
| 1 | contribution | | | | | | |

Calculate:

```text
engine_unattributed =
    engine total
    - sum of non-overlapping top-level engine phases

rest_unattributed =
    REST total
    - engine total
    - JSON serialization

pre_first_byte_gap =
    HTTP time_starttransfer
    - REST total
```

Do not add nested category times to their parent total a second time.

Small differences from logging, framework overhead, clock boundaries, and
rounding are expected. Large differences need another timer rather than an
assumption.

## How to interpret the phase results

### If temporary foreground creation dominates

Investigate:

- repeated database creation/deletion;
- Brightway metadata flushes;
- SQLite/database writes;
- filesystem latency;
- whether both calls can safely reuse a prepared foreground keyed by
  `result_id`; and
- cleanup cost hidden inside the combined phase.

The likely fix would be bounded server-side reuse with a TTL and explicit
cleanup. Do not reuse mutable Brightway state across concurrent requests
without understanding locking and project isolation.

### If `lci_factorization` dominates both calls

The strongest explanation is repeated sparse setup/factorization plus slower
single-core performance on the shared-vCPU droplet.

Compare these options with measurements:

1. Reuse prepared calculation state between Call 1 and Call 2, keyed by
   `result_id`, with bounded memory and expiry.
2. Avoid rebuilding identical foreground and LCI state in Call 2.
3. Test `pypardiso` in a disposable diagnostic image.
4. Compare against a dedicated-vCPU droplet or the faster Linux workstation.

Do not install `pypardiso` into the running container. A proper experiment
requires:

- a Dockerfile/dependency change;
- a disposable image;
- the same test graph and categories;
- correctness comparison with the existing solver;
- cold and warm timings;
- memory measurement; and
- no use of the live Brightway volume by a second calculation process.

### If adjoint transpose factorization dominates contribution

Investigate whether the transpose factorization can be cached or replaced by a
solver that performs better for repeated transposed solves. Preserve the
adjoint reconciliation checks and regression coverage.

### If per-category LCIA dominates

Measure method switching, characterization, and direct contribution
construction separately. Reuse inventory where safe and avoid recomputing
category-independent structures.

### If contribution traversal dominates

Profile the traversal algorithm with the exact 73-node and 85-node results.
Look for repeated sparse solves, repeated graph/database lookups, ineffective
memoization, or work performed below the cutoff. Do not loosen cutoff or
accuracy settings merely to make the benchmark faster.

### If JSON serialization dominates

Consider a faster serializer and HTTP compression, then prove serialized
content equivalence. Compression is worthwhile for bandwidth but cannot
explain a long delay before the first byte if serialization is small.

### If calculation-lock waiting or REST overhead dominates

Repeat only one request at a time and inspect concurrent traffic. A global
in-process calculation lock can serialize requests. Do not remove the lock
until Brightway shared-state safety is demonstrated.

### If all compute phases are proportionally slower

The host's per-core performance is the leading explanation. Run the same
controlled workload on:

- the developer Mac;
- the reportedly faster Linux workstation;
- the current shared-vCPU droplet; and
- optionally a dedicated-vCPU DigitalOcean instance.

Use identical Python dependencies where practical. Report CPU model, Python,
NumPy, SciPy, solver, phase timings, and result equality.

### If named phases do not explain total time

Do not guess. Add the smallest missing timers, likely:

- calculation-lock acquisition wait;
- foreground cleanup;
- base-result/Sankey subphases;
- REST request parsing; or
- method lookup/configuration.

Deploy a second instrumentation revision only if the unexplained portion is
large enough to affect the optimization decision.

## Performance-fix design constraints

Any proposed permanent fix must preserve:

- both public endpoint contracts;
- lazy two-stage loading in the product editor;
- deterministic/correct `result_id` behavior;
- all LCA scores and contribution graph content;
- category ordering and labels;
- impact cutoff semantics;
- request isolation;
- Brightway project/database safety;
- bounded memory and disk usage;
- cleanup after errors and expiry; and
- correct behavior across process or container restarts.

If caching calculation state:

- define the cache key explicitly;
- define TTL and maximum entries/bytes;
- handle stale/missing entries by recomputing safely;
- prevent one request from reading another user's mutable state;
- coordinate with the calculation lock;
- define behavior with multiple Uvicorn workers or replicas;
- do not rely on in-memory state without documenting loss on restart; and
- add tests for expiry, fallback, concurrency, and result equality.

If changing the sparse solver:

- pin the dependency;
- check architecture and Python wheel availability;
- document image-size and startup impact;
- compare factorization and solve times separately;
- compare numerical results with tolerances justified by existing tests;
- retain a fallback if the optional solver is unavailable; and
- test the production container architecture, not only the Mac.

## Safety boundaries

Never do any of the following without explicit approval:

- restart or stop the LCA container;
- deploy through Coolify;
- edit files inside the running container;
- `pip install` or `uv add` inside the running container;
- alter Coolify CPU, memory, networking, or environment settings;
- resize the droplet;
- modify or delete the production Brightway volume;
- run a second Brightway calculation process against the live volume;
- remove the calculation lock;
- enable concurrent LCA calculations;
- commit or push code;
- discard the existing instrumentation patch; or
- print secrets, environment variables, Docker labels, or authentication
  files.

Read-only Docker inspection is safe when the exact container is resolved.
Public API requests are safe when run sequentially and in reasonable numbers.

## Required final report

Return a concise evidence-based report containing:

1. Exact repository state and patch files.
2. Tests run and exact results.
3. Instrumentation commit SHA, only if the user authorized a commit.
4. Deployment confirmation supplied by the user.
5. Three-run HTTP timings.
6. Three-run engine and REST phase timings.
7. Dominant phase for each endpoint.
8. Named versus unattributed time.
9. Correctness comparison across all runs.
10. The most likely root cause.
11. The smallest recommended permanent fix.
12. One controlled alternative experiment.
13. Risks and rollback plan.
14. Actions that still require user approval.

The investigation is not complete merely because the server is slow or
because `pypardiso` is missing. It is complete when measured phase data
identifies the dominant work and supports a specific, testable fix.
