# Production LCA Performance Investigation

Use this document as the initial prompt/context for Codex running on the
DigitalOcean droplet that hosts the production LCA service.

## Objective

Determine why the production LCA engine takes approximately 36 seconds to run
the two-stage Plastic Broom calculation while the same calculation takes
approximately 6 seconds on the developer's Mac.

Start with read-only diagnostics. Do not restart services, change Coolify
settings, install packages, edit the running container, modify the Brightway
volume, or deploy code without explicit approval.

## Service and repository

- Repository: `https://github.com/calvinw/life-cycle-assessment-mcp`
- Production service: `https://lca-mcp.mathplosion.com`
- Production health: `https://lca-mcp.mathplosion.com/api/health`
- Expected deployed fix commit: `25881c7`
- Runtime: FastMCP/Uvicorn, Brightway 2.5, Docker, managed by Coolify
- Production image base: `python:3.11-slim`

The correctness fix in `25881c7` changes only the adjoint-score numerical
reconciliation tolerance and adds a real BAFU Plastic Broom regression test.
It is not intended to improve performance.

## Confirmed behavior

The exact production two-stage flow succeeds after deploying `25881c7`:

| Stage | Production | Local Mac |
|---|---:|---:|
| `POST /api/lca/base` | 20.53 s | 3.10 s |
| `POST /api/lca/contribution` for two categories | 15.48 s | 2.87 s |
| Combined | 36.00 s | 5.97 s |

Production response sizes without HTTP compression:

- Base response: 724,648 bytes
- Two-category contribution response: 240,368 bytes

Production currently does not return `Content-Encoding` when the client sends
`Accept-Encoding: gzip, br`.

The contribution response contains:

- Acidification: 73 nodes, 72 edges, 40 flows
- Climate change: 85 nodes, 84 edges, 39 flows

Both contribution graphs have `status: "partial"` because of the configured
impact cutoff. That status is expected and is not an error.

## Relevant local numerical environment

The faster local Mac is Apple Silicon and currently reports:

- Python 3.14.1
- NumPy 2.4.6 using Apple Accelerate
- SciPy 1.18.0
- `scikits.umfpack`: not installed
- `pypardiso`: not installed
- `sksparse`: not installed
- Sparse adjoint factorization: `scipy.sparse.linalg.splu`/SuperLU

The production lockfile selects SciPy 1.17.1 under Python 3.11. Therefore, do
not assume the Mac is faster merely because it has UMFPACK or Pardiso; it does
not. Possible causes include droplet CPU performance, shared-vCPU contention,
container CPU/memory limits, swapping, SciPy/platform differences, database
I/O, and JSON serialization.

## Safety requirements

1. Begin with read-only host and container inspection.
2. Resolve the exact LCA container before using `docker exec`; do not guess.
3. Do not print environment variables, authentication files, API keys, Coolify
   secrets, or the contents of Docker labels that may contain secrets.
4. Do not run a second in-process Brightway calculation directly against the
   live Brightway volume while the web service is accepting traffic. The
   Python calculation lock is process-local and will not protect two separate
   processes.
5. Use the public REST endpoints for live benchmarks.
6. Internal profiling must use either:
   - a controlled diagnostic build with timing logs;
   - a separate disposable container with a copied Brightway data volume; or
   - an approved maintenance window with normal traffic stopped.
7. Do not restart, redeploy, resize, or modify production without approval.

## Phase 1: identify the deployment

Find the relevant container without changing anything:

```bash
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
```

Set a task-specific variable only after confirming the exact container:

```bash
LCA_CONTAINER_ID='<confirmed-container-id>'
```

Confirm that the running code includes the tolerance fix:

```bash
docker exec "$LCA_CONTAINER_ID" python -c \
  'from lca_core.contribution_graph import ADJOINT_SCORE_REL_TOLERANCE; print(ADJOINT_SCORE_REL_TOLERANCE)'
```

Expected value:

```text
1e-08
```

Do not inspect or print the full container environment.

## Phase 2: host and container resources

Record:

```bash
uname -a
lscpu
nproc
free -h
uptime
df -h
docker stats --no-stream "$LCA_CONTAINER_ID"
```

Inspect only resource-related container settings:

```bash
docker inspect --format \
  'NanoCpus={{.HostConfig.NanoCpus}} CpuQuota={{.HostConfig.CpuQuota}} CpuPeriod={{.HostConfig.CpuPeriod}} CpusetCpus={{.HostConfig.CpusetCpus}} Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}}' \
  "$LCA_CONTAINER_ID"
```

Inside the container, record visible cgroup limits where available:

```bash
docker exec "$LCA_CONTAINER_ID" sh -lc '
  python --version
  nproc
  test -r /sys/fs/cgroup/cpu.max && cat /sys/fs/cgroup/cpu.max
  test -r /sys/fs/cgroup/memory.max && cat /sys/fs/cgroup/memory.max
  test -r /sys/fs/cgroup/memory.current && cat /sys/fs/cgroup/memory.current
'
```

Pay particular attention to:

- a fractional CPU quota;
- one shared vCPU;
- memory near the cgroup maximum;
- active swap;
- high host load or steal time; and
- other containers competing for CPU.

If available without installing anything, sample CPU behavior during one API
request with `vmstat 1` or equivalent. Report CPU wait and steal separately
from ordinary user CPU.

## Phase 3: numerical-library inspection

Run this read-only inspection inside the confirmed container:

```bash
docker exec "$LCA_CONTAINER_ID" python - <<'PY'
import importlib.util
import platform

import numpy as np
import scipy
import scipy.sparse.linalg as sla

print("platform:", platform.platform())
print("machine:", platform.machine())
print("python:", platform.python_version())
print("numpy:", np.__version__)
print("scipy:", scipy.__version__)
for name in ("scikits.umfpack", "pypardiso", "sksparse"):
    try:
        found = importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        found = False
    print(f"{name}:", found)
print("splu module:", sla.splu.__module__)
print("NumPy build configuration:")
np.show_config()
PY
```

If `threadpoolctl` is already installed, also run:

```bash
docker exec "$LCA_CONTAINER_ID" python - <<'PY'
from threadpoolctl import threadpool_info
for item in threadpool_info():
    print({
        "internal_api": item.get("internal_api"),
        "prefix": item.get("prefix"),
        "version": item.get("version"),
        "num_threads": item.get("num_threads"),
        "architecture": item.get("architecture"),
    })
PY
```

Do not install `threadpoolctl` merely for this check.

## Phase 4: repeat the public API benchmark

Use the exact checked-in file
`bafu_examples/plastic_broom.yaml` from a repository checkout outside the
running container. Do not copy it into the production container.

Create request files in a temporary directory:

```bash
LCA_VERIFY_DIR="$(mktemp -d /tmp/lca-broom-profile.XXXXXX)"
jq -Rs '{product_graph: .}' bafu_examples/plastic_broom.yaml \
  > "$LCA_VERIFY_DIR/base-request.json"
```

Run Call 1:

```bash
curl --silent --show-error --max-time 120 \
  -o "$LCA_VERIFY_DIR/base-response.json" \
  -w 'base http=%{http_code} connect=%{time_connect}s ttfb=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' \
  -H 'Content-Type: application/json' \
  --data-binary @"$LCA_VERIFY_DIR/base-request.json" \
  https://lca-mcp.mathplosion.com/api/lca/base
```

Build the exact product-editor Call 2 request:

```bash
LCA_RESULT_ID="$(jq -r '.result_id' "$LCA_VERIFY_DIR/base-response.json")"
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
  > "$LCA_VERIFY_DIR/contribution-request.json"
```

Run Call 2:

```bash
curl --silent --show-error --max-time 120 \
  -o "$LCA_VERIFY_DIR/contribution-response.json" \
  -w 'contribution http=%{http_code} connect=%{time_connect}s ttfb=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n' \
  -H 'Content-Type: application/json' \
  --data-binary @"$LCA_VERIFY_DIR/contribution-request.json" \
  https://lca-mcp.mathplosion.com/api/lca/contribution
```

Confirm correctness without printing the full responses:

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
}' "$LCA_VERIFY_DIR/contribution-response.json"
```

Run the pair at least three times sequentially and record every result. Do not
run them concurrently yet. Compare the first run with later warm runs.

While one pair is running, sample:

```bash
docker stats "$LCA_CONTAINER_ID"
```

Stop the sampler after the request completes. Record peak CPU and memory rather
than pasting an unbounded stream of samples.

## Phase 5: locate the slow phase

First inspect the implementation paths:

- `lca_core/engine.py::run_base_analysis`
- `lca_core/engine.py::_run_analysis`
- `lca_core/engine.py::run_contribution_analysis`
- `lca_core/contribution_graph.py::factorize_adjoint`
- `lca_core/contribution_graph.py::build_contribution_graph`
- `lca_server.py::api_run_lca_base`
- `lca_server.py::api_get_lca_contribution_graphs`

The two stateless API stages both rebuild the temporary foreground database and
repeat LCI setup/factorization. That shared work is a likely explanation if
both endpoints consume similar CPU time.

Propose minimal timing instrumentation that separately measures:

1. YAML parsing and validation
2. Brightway project readiness
3. temporary foreground creation
4. LCA construction
5. `lci(factorize=True)`
6. adjoint `A.T` factorization
7. LCIA method switching/calculation
8. direct process-contribution construction
9. contribution traversal per category
10. result validation
11. JSON serialization
12. response transfer

Do not add noisy per-node logs. Use one structured timing summary per request.
Do not deploy the instrumentation until the user approves the patch.

## Questions to answer

Return a concise report answering:

1. Is commit `25881c7` definitely running?
2. What CPU and memory limits does the container actually have?
3. Is the host under load or showing CPU steal/throttling?
4. Which BLAS/LAPACK and sparse solver implementations are present?
5. Are optional UMFPACK/Pardiso packages present?
6. Are repeated warm runs faster than the first run?
7. Does CPU stay near the container limit during each request?
8. Is memory pressure or swapping visible?
9. How much of Call 1 is transfer time versus server time?
10. What is the smallest next experiment that will identify the dominant
    internal phase?

## Do not jump directly to these changes

Do not install UMFPACK, Pardiso, MKL, OpenBLAS packages, or change thread counts
until measurements show that sparse factorization is the bottleneck. Do not
increase the droplet size until CPU quota/contention has been measured. Do not
remove the global calculation lock or enable concurrent calculations during
this diagnostic pass.

HTTP compression is independently worthwhile, but it will reduce transfer
time and payload size, not explain all of the 5–6x server-side slowdown.
