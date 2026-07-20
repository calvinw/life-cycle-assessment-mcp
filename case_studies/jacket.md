## About this analysis

A cradle-to-gate LCA for one finished jacket. The product graph contains five
foreground processes across a three-tier textile chain plus a separate zipper
branch. It is designed to demonstrate compound scaling, branching Sankey flows,
and process contributions across multiple impact categories.

### Supply chain

```text
Raw material extraction → Spinning → Fabric weaving ─┐
                                                     ├→ Jacket assembly [reference]
                         Zipper production ──────────┘
```

Jacket assembly consumes 0.6 kg of fabric and one zipper. Each kilogram of
fabric requires 1.1 kg of fiber, and each kilogram of fiber requires 1.2 kg of
raw fiber material.

### Scaling factors

| Process | Scaling factor | Derivation |
|---|---:|---|
| P0 — Raw material extraction | 0.792 | 0.6 × 1.1 × 1.2 |
| P1 — Spinning | 0.660 | 0.6 × 1.1 |
| P2 — Fabric weaving | 0.600 | Fabric input per jacket |
| P3 — Zipper production | 1.000 | One zipper per jacket |
| P4 — Jacket assembly | 1.000 | Reference process |

### LCIA method and results

The analysis uses TRACI v2.1. Nonzero impact results for one jacket are:

| Impact category | Total |
|---|---:|
| Climate change | 4.878600 kg CO2-Eq |
| Photochemical oxidant formation | 0.273052 kg O3-Eq |
| Acidification | 0.007700 kg SO2-Eq |
| Eutrophication | 0.000487 kg N-Eq |
| Particulate matter formation | 0.0000794 PM2.5-Eq |

### Climate-change contributions

| Process | Direct score | Percentage |
|---|---:|---:|
| P0 — Raw material extraction | 1.821600 kg CO2-Eq | 37.34% |
| P1 — Spinning | 0.957000 kg CO2-Eq | 19.62% |
| P2 — Fabric weaving | 0.900000 kg CO2-Eq | 18.45% |
| P3 — Zipper production | 0.400000 kg CO2-Eq | 8.20% |
| P4 — Jacket assembly | 0.800000 kg CO2-Eq | 16.40% |

The exclusive process scores reconcile with the category total. Nitrogen oxide
from fabric weaving and zipper production drives the acidification,
eutrophication, and particulate-matter results.

### Key teaching points

- Compound scaling propagates the 0.6 kg fabric demand through spinning to
  0.792 kg of raw fiber material.
- The zipper is a separate branch with a scaling factor of one, demonstrating
  a graph that branches before joining at assembly.
- The largest climate hotspot is raw material extraction, while fabric weaving
  and zipper production dominate several nitrogen-oxide-related categories.
- Sankey links retain separate `kg` and `unit` quantities; their widths should
  only be compared within compatible units.

### Simplifications

- Material identities and direct emissions are illustrative.
- Transport, dyeing, finishing, use, and end-of-life are not included.
- Background energy and infrastructure processes are not modeled separately.
