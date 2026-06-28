# Plan: Database Stacks — Multi-Profile Brightway Setup

## Overview

Support multiple "stacks" — named combinations of biosphere database + LCI
background database + LCIA methods — that can be selected at calculation time
without restarting the container.

---

## What Is a Stack

A stack is a consistent, UUID-compatible combination of three components:

| Component | Role |
|---|---|
| Biosphere database | Elementary flows (CO₂, water, land use, etc.) |
| LCI background database | Upstream process inventory (BAFU, USLCI, etc.) |
| LCIA methods | Characterization factors keyed to the biosphere UUIDs |

Mixing components across stacks silently zeros impact contributions (UUID
mismatch bug — same class of bug as the N2O sub-compartment fix, June 2026).

---

## Planned Stacks

| Stack name | Biosphere | LCI database | LCIA methods |
|---|---|---|---|
| `default` | `biosphere3` | none (foreground only) | TRACI v2.1 |
| `swiss` | `biosphere3` | `bafu` (BAFU:2025) | Ecological Scarcity 2021, EF v3.1 |
| `us` | `fedefl` | `uslci` | TRACI v2.1 |

The `default` stack is the current production state. Others are additive —
they share the same Brightway project and volume.

---

## Volume Strategy — Pre-Built Tarballs

### Problem

Importing databases at container startup is slow, network-dependent, and
blocks the server from starting. The old FEDEFL + openLCA LCIA zip was 158 MB
and took minutes.

### Solution

Pre-build the `brightway_data/` directory locally with all databases imported,
then tar and upload to a GitHub release. Container first boot downloads the
tarball and extracts it — subsequent boots skip entirely (idempotent check).

```
GitHub Releases:
  brightway_default_v1.tar.gz    — biosphere3 + 762 LCIA methods (~70 MB compressed)
  brightway_swiss_v1.tar.gz      — above + BAFU:2025 (~120 MB est.)
  brightway_full_v1.tar.gz       — all stacks combined
```

### Lazy Loading (preferred approach)

Rather than selecting a tarball at deploy time, the server can download stack
components on first use:

```
run_lca(recipe_card=..., stack="swiss")
  → _ensure_stack("swiss")
      → if "bafu" not in bd.databases:
            download bafu tarball (~8 sec on DO droplet)
            extract into /app/brightway_data
      → proceed with LCA
```

**Download time estimates** (Digital Ocean droplet, GitHub releases):
- `default` tarball: ~70 MB → 2–5 seconds
- `swiss` addition: ~50 MB incremental → 2–4 seconds
- First call to new stack blocks once, then instant forever

**Concurrency**: use a per-stack `threading.Lock` to prevent duplicate
downloads if two MCP calls request the same unloaded stack simultaneously.

### `_ensure_stack()` sketch

```python
_stack_locks: dict[str, threading.Lock] = {}

STACK_RELEASE_URLS = {
    "swiss": "https://github.com/calvinw/life-cycle-assessment-mcp"
             "/releases/download/lca-data-v2/brightway_swiss_v1.tar.gz",
    "us":    "https://github.com/calvinw/life-cycle-assessment-mcp"
             "/releases/download/lca-data-v2/brightway_us_v1.tar.gz",
}

STACK_DATABASES = {
    "default": [],
    "swiss": ["bafu"],
    "us": ["fedefl", "uslci"],
}

def _ensure_stack(stack: str):
    needed = STACK_DATABASES.get(stack, [])
    missing = [db for db in needed if db not in bd.databases]
    if not missing:
        return
    lock = _stack_locks.setdefault(stack, threading.Lock())
    with lock:
        # Re-check after acquiring lock
        missing = [db for db in needed if db not in bd.databases]
        if not missing:
            return
        url = STACK_RELEASE_URLS[stack]
        _download_and_extract(url)
```

---

## Engine Changes

### `lca_engine.py`

`BIOSPHERE_DB` and `FOREGROUND_DB` become per-stack lookups:

```python
STACK_CONFIG = {
    "default": {
        "biosphere": "biosphere3",
        "lci_databases": [],
        "lcia_family": "TRACI v2.1",
    },
    "swiss": {
        "biosphere": "biosphere3",
        "lci_databases": ["bafu"],
        "lcia_family": "Ecological Scarcity 2021",
    },
    "us": {
        "biosphere": "fedefl",
        "lci_databases": ["uslci"],
        "lcia_family": "TRACI v2.1",
    },
}
```

`_FLOW_INDEX` becomes a dict keyed by biosphere name:
```python
_FLOW_INDEX: dict[str, dict] = {}   # biosphere_name → {(name, compartment) → key}
```

### Recipe card changes

One optional new field:

```yaml
stack: swiss   # default if omitted: "default"
```

Existing recipe cards without `stack:` continue to work unchanged.

---

## Search Across Stacks

`search_database()` already supports arbitrary database names. Once BAFU is
imported, searching across stacks requires no engine changes:

```python
search_database("cotton", database="biosphere3")  # default stack flows
search_database("cotton", database="bafu")         # BAFU processes
```

`list_databases()` shows all currently loaded databases regardless of stack.

---

## BAFU:2025 Import Notes

- Format: EcoSpold V1 (for Brightway) — available free on openLCA Nexus
- Importer: `bw2io.SingleOutputEcospold1Importer`
- ~11,000 datasets across 176 categories
- Biosphere flows use ecoinvent naming → compatible with `biosphere3`
- LCIA methods already installed: Ecological Scarcity 2021 (20 categories),
  EF v3.1 (25 categories)
- Known issue: EcoSpold 1 export from openLCA Desktop has schema violations
  (`firstAuthor` maxLength, `CASNumber` pattern). May need XML preprocessing
  before import.

---

## Implementation Order

1. **Verify BAFU import** — download from Nexus, attempt
   `SingleOutputEcospold1Importer`, fix schema violations if needed
2. **Build `brightway_swiss` tarball** — import BAFU locally, tar
   `brightway_data/`, upload to GitHub release
3. **Add `_ensure_stack()`** to `lca_engine.py` with lazy download
4. **Parameterise `BIOSPHERE_DB`** — thread `stack` arg through
   `run_analysis()`, `_find_biosphere_flow()`, `_FLOW_INDEX`
5. **Add `stack:` field** to recipe card spec and engine parser
6. **Update `run_lca` MCP tool** — expose `stack` parameter
7. **Add USLCI stack** — same pattern, different tarball

---

## Open Questions

1. Should the `stack` field be in the recipe card YAML or passed as a separate
   `run_lca()` argument? Separate arg is more flexible; YAML is more
   reproducible/self-contained.

2. What happens when `list_databases()` is called and a stack hasn't been
   lazy-loaded yet — should it list only loaded databases, or declare all
   known stacks regardless?

3. Is a combined `brightway_full_v1.tar.gz` worth maintaining, or always
   lazy-load per stack?
