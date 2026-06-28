# Plan: Unified SVG Engine for Recipe Cards and BAFU Background Processes

## Current State

There are currently **two separate SVG pipelines** that work differently:

### Pipeline 1 — `lca_svg.py` (recipe cards)

Used by `lca_svg_engine.py` and the MCP tools `get_lca_svg` and `get_unit_process_svg`.

**Input:** Recipe card YAML (foreground-only, hand-authored)

**Approach:**
1. Parse YAML to get processes, flows, emissions, resources
2. Build a graphviz `.dot` description
3. Run `dot -Tplain` to get node/edge positions as numbers
4. Render **pure SVG by hand** from those positions using helper functions:
   - `svg_rect()`, `svg_text()`, `svg_line()` etc.
   - `svg_chem_text()` for chemical subscripts (CO₂ not CO2)
   - `elementary_flows()` — red emission arrows below each box, green resource arrows above
   - `tech_edges()` — technosphere flow arrows with scaled amounts
   - `process_boxes()` — process boxes with scaling factor labels

**Features:**
- Process boxes (blue) and functional unit box (purple)
- Technosphere edges labelled with flow name + scaled amount + unit
- Elementary flow arms: emissions (red, below) and resources (green, above)
- Proper chemical subscripts: CO₂, CH₄, N₂O
- Scaling factors shown on each process box (s1 = 0.52 etc.)
- "to Air", "from Nature" labels on biosphere arrows

**Limitation:** Only works for explicitly-authored foreground recipe cards.
Cannot handle background BAFU processes automatically.

---

### Pipeline 2 — `scripts/bafu_graph_svg.py` (BAFU background processes)

**Input:** Any Brightway activity (BAFU process or foreground activity)

**Approach:**
1. Run `bc.LCA` + `NewNodeEachVisitGraphTraversal` from `bw_graph_tools`
2. Get nodes (with cumulative LCIA scores) and edges (with amounts)
3. Build a graphviz `.dot` description
4. Run `dot -Tsvg` — let graphviz render the SVG directly

**Features:**
- Process boxes with cumulative impact score and % of total
- Technosphere edges labelled with exchange amounts
- Functional unit box (purple)
- Depth-based colouring (blue for depth-1, light blue for deeper)

**Limitations:**
- No elementary flow arms (emissions/resources not shown)
- No scaling factors
- No chemical subscripts
- Graphviz controls styling — less flexibility than hand-rendered SVG
- Uses `dot -Tsvg` so we can't post-process node positions

---

## Proposed Unified Engine

Replace both pipelines with a single engine that:

1. Accepts **either** a recipe card YAML **or** a Brightway activity as input
2. Uses `bw_graph_tools` traversal for the actual LCA computation in both cases
3. Uses `dot -Tplain` + hand-rendered SVG (Pipeline 1's approach) for all output
4. Adds elementary flow arms to BAFU background processes by reading biosphere
   exchanges directly from the Brightway database

### Architecture

```
Input (one of):
  A) Recipe card YAML  →  build foreground db  →  run LCA
  B) Brightway activity  →  run LCA directly

         ↓
  NewNodeEachVisitGraphTraversal
  (nodes with cumulative scores, edges with amounts)

         ↓
  For each node: pull direct biosphere exchanges from bw2data
  (top N emitters by characterization factor × amount)

         ↓
  Build unified graph data structure:
    nodes: [{name, location, unit, cum_score, pct, direct_score, 
             emissions: [{flow, amount, unit, cf}],
             resources: [{flow, amount, unit}]}]
    edges: [{src, dst, amount, unit, flow_name}]

         ↓
  dot -Tplain  →  get node/edge positions

         ↓
  Hand-render SVG using lca_svg.py helper functions:
    - process_boxes()  →  blue/purple boxes with scores + scaling
    - tech_edges()     →  technosphere arrows with amounts + units
    - elementary_flows()  →  red/green arms with chem subscripts
    - title + legend
```

### Key implementation steps

1. **Extract `dot -Tplain` renderer from `lca_svg.py`** into shared helpers
   (`svg_rect`, `svg_text`, `svg_line`, `svg_chem_text`, `parse_plain` etc.)
   Move to a new `lca_svg_helpers.py` module.

2. **Write `build_graph_data(lca, result, bd, method)`** — takes a `bw_graph_tools`
   result and returns the unified graph data structure above. Includes:
   - Resolving matrix indices → activity names + locations
   - Pulling top biosphere exchanges per node (limit to top 3–5 by impact)
   - Computing direct vs. upstream split

3. **Write `render_svg(graph_data, dot_plain_output)`** — takes the unified graph
   data and dot positions, produces SVG using shared helpers.

4. **New entry point `generate_bafu_svg(activity, method, ...)`** — calls LCA,
   traversal, build_graph_data, dot, render_svg.

5. **Adapt `lca_svg.py:generate()`** to use the same render_svg path for
   recipe cards, replacing the current parallel implementation.

### What stays the same
- `lca_svg_engine.py` — thin wrapper, no changes needed
- `lca_server.py` MCP tools — no changes needed
- Recipe card YAML format — no changes needed
- `generate_unit_process()` — can stay as-is (single process card, different layout)

### SVG visual additions for BAFU graphs
- Top 3–5 direct emissions per node as red arms (CO₂, CH₄, N₂O etc.)
- Extraction flows (energy, water, land) as green arms above
- Scaling factor on each node (activity level from `lca.supply_array`)
- Edge labels: flow name + amount + unit (not just the number)

---

## Files affected

| File | Change |
|------|--------|
| `lca_svg.py` | Refactor to use shared helpers; expose renderer |
| `lca_svg_helpers.py` | New — shared SVG primitives extracted from lca_svg.py |
| `scripts/bafu_graph_svg.py` | Rewrite to use shared renderer + add bio arms |
| `lca_svg_engine.py` | Minor — call new entry point for BAFU graphs |
| `lca_server.py` | Add new MCP tool `get_bafu_svg(process_name, location)` |

---

## Not in scope

- Sankey diagrams (separate effort, different layout algorithm)
- Contribution bar charts (separate effort)
- Multi-method comparison graphs
- `generate_unit_process()` refactor
