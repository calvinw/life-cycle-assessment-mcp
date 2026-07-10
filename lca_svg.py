#!/usr/bin/env python3
"""
lca_svg.py  —  Generate an LCA product-system SVG from a product_graph.yaml file.

This script produces two types of supply chain diagrams:
  • Scaled graph    — shows flow amounts and scaling factors (default)
  • Structure graph — shows flow names only (use --structure)

It is also called automatically by lca_analysis.py after the LCA calculation
step (Step 14 in the report). No separate command is needed during a normal
analysis workflow.

┌─────────────────────────────────────────────────────────────────────┐
│ USAGE                                                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   # Scaled graph (with amounts + scaling factors)                   │
│   python3 lca_svg.py lca_analysis/coffee/product_graph.yaml           │
│                                                                     │
│   # Structure graph (flow names only)                               │
│   python3 lca_svg.py lca_analysis/coffee/product_graph.yaml --structure │
│                                                                     │
│   # Specify output path                                             │
│   python3 lca_svg.py product_graph.yaml my_graph.svg                  │
│                                                                     │
│   # Or the default — just pass the product graph path:                │
│   #   python3 lca_svg.py lca_analysis/coffee/product_graph.yaml       │
│   #   →  writes lca_analysis/coffee/product_graph.svg                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

Prerequisites:
  • Python 3 with numpy, pyyaml, olca-schema (no olca-ipc needed for SVG)
  • graphviz (dot command) — installed in the devcontainer base image

Layout engine: graphviz dot (left-to-right DAG ranking)
Rendering:     pure SVG built from dot -Tplain node positions
"""

import sys
import re
import subprocess
import numpy as np
import yaml
from pathlib import Path


# ── Style constants ────────────────────────────────────────────────────────────
COL_PROCESS   = '#3a7ebf'
COL_BACKGROUND = '#888888'
COL_FU        = '#7b4ea6'
COL_TECH_EDGE = '#555555'
COL_GREEN     = '#2d7a45'
COL_RED       = '#c0392b'
FONT          = 'Helvetica,Arial,sans-serif'

BOX_W, BOX_H  = 165, 54
FU_W,  FU_H   = 165, 66
MARGIN        = 60          # px around the graphviz bounding box
ELEM_ARM      = 30          # length of elementary flow arrows
EMIT_OFFSET   = 45          # ±px horizontal offset for multiple emissions
TITLE_HEIGHT  = 38          # px reserved for title above the graph

# Map biosphere3 flow names → short chemistry symbols for diagram labels.
# chem_sub() will then render digits as proper SVG subscripts (CO2 → CO₂).
FLOW_DISPLAY = {
    "Carbon dioxide":  "CO2",
    "Methane":         "CH4",
    "Nitrous oxide":   "N2O",
    "Ammonia":         "NH3",
    "Nitrogen oxides": "NOx",
    "Sulfur dioxide":  "SO2",
    "Water":           "H2O",
}


def _display_name(flow_name: str) -> str:
    """Return a short chemistry symbol for biosphere3 flows, or the name unchanged."""
    return FLOW_DISPLAY.get(flow_name, flow_name)

DPI           = 96          # graphviz uses 72 pt; we scale to 96px


# ── YAML parsing ──────────────────────────────────────────────────────────────
def load_recipe(path: str) -> dict:
    text = Path(path).read_text()
    # strip markdown fences if present
    m = re.search(r'^---\n(.*?)^---', text, re.DOTALL | re.MULTILINE)
    if m:
        return yaml.safe_load(m.group(1))
    return yaml.safe_load(text)


# ── Graphviz plain layout ──────────────────────────────────────────────────────
def run_dot_plain(recipe: dict) -> str:
    """Build a dot graph and return dot -Tplain output."""
    lines = ['digraph G {']
    lines.append('  rankdir=LR;')
    lines.append('  nodesep=1.2;')
    lines.append('  ranksep=0.6;')
    lines.append('  node [shape=rectangle, width=1.8, height=0.6, fixedsize=true];')
    lines.append('  edge [fontsize=11];')

    # process nodes
    for p in recipe['processes']:
        name = p['name']
        lines.append(f'  "{name}" [];')

    # functional unit node — height grows with wrapped description
    fu = recipe['functional_unit']
    desc_lines = len(wrap_text(fu['description']).split('\n'))
    fu_height = round(0.75 + (desc_lines - 1) * 0.18, 2)
    lines.append(f'  "Functional Unit" [width=1.8, height={fu_height}];')

    # background input nodes (database: bafu etc.) — rendered as grey boxes
    # height grows to fit wrapped text
    bg_nodes = set()
    for p in recipe['processes']:
        for inp in p.get('inputs', []):
            if inp.get('database') and not _producer(recipe, inp['flow']):
                node_id = inp['flow']
                if node_id not in bg_nodes:
                    bg_nodes.add(node_id)
                    lines.append(f'  "{node_id}" [style=filled, fillcolor="#cccccc"];')

    # technosphere edges (process → process, and background → process)
    ref = recipe['reference_process']
    for p in recipe['processes']:
        for inp in p.get('inputs', []):
            src = _producer(recipe, inp['flow'])
            if src:
                label = inp["flow"]
                lines.append(f'  "{src}" -> "{p["name"]}" [label="{label}"];')
            elif inp.get('database'):
                label = inp["flow"]
                lines.append(f'  "{inp["flow"]}" -> "{p["name"]}" [label="{label}"];')

    # edge from reference process to functional unit
    ref = recipe['reference_process']
    ref_out = _ref_process(recipe, ref)
    fu_label = ref_out["reference_output"]["flow"]
    lines.append(f'  "{ref}" -> "Functional Unit" [label="{fu_label}"];')

    lines.append('}')
    dot_src = '\n'.join(lines)

    result = subprocess.run(
        ['dot', '-Tplain'],
        input=dot_src.encode(),
        capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"dot failed: {result.stderr.decode()}")
    return result.stdout.decode()


def _producer(recipe: dict, flow_name: str) -> str | None:
    for p in recipe['processes']:
        if p['reference_output']['flow'] == flow_name:
            return p['name']
    return None


def _ref_process(recipe: dict, name: str) -> dict:
    for p in recipe['processes']:
        if p['name'] == name:
            return p
    raise KeyError(name)


def _flow_unit(recipe: dict, flow_name: str) -> str:
    for f in recipe.get('products', []):
        if f['name'] == flow_name:
            return f['unit']
    return ''


# ── Scaling vector solver ─────────────────────────────────────────────────────
def compute_scaling(recipe: dict) -> dict:
    """Solve A·s = f and return {process_name: scaling_factor}."""
    order = [p['name'] for p in recipe['processes']]
    proc_map = {p['name']: p for p in recipe['processes']}
    products = [p['name'] for p in recipe['products']]

    n = len(order)
    m = len(products)
    A = np.zeros((m, n))

    for j, pname in enumerate(order):
        ps = proc_map[pname]
        ro = ps['reference_output']
        if ro['flow'] in products:
            A[products.index(ro['flow']), j] = ro['amount']
        for inp in ps.get('inputs', []):
            if inp['flow'] in products:
                A[products.index(inp['flow']), j] -= inp['amount']

    ref_ro = proc_map[recipe['reference_process']]['reference_output']
    f = np.zeros(m)
    if ref_ro['flow'] in products:
        f[products.index(ref_ro['flow'])] = recipe['functional_unit']['amount']

    s_vec = np.linalg.solve(A, f)
    return {pname: float(s_vec[j]) for j, pname in enumerate(order)}


# ── Parse dot -Tplain ──────────────────────────────────────────────────────────
def tokenize_plain(line: str) -> list[str]:
    """Split a dot -Tplain line respecting double-quoted tokens."""
    tokens = []
    i = 0
    while i < len(line):
        if line[i].isspace():
            i += 1
        elif line[i] == '"':
            j = i + 1
            while j < len(line) and line[j] != '"':
                j += 1
            tokens.append(line[i+1:j])
            i = j + 1
        else:
            j = i
            while j < len(line) and not line[j].isspace():
                j += 1
            tokens.append(line[i:j])
            i = j
    return tokens


def parse_plain(plain: str, scale: float):
    """
    Returns:
        graph_w, graph_h  — canvas size in px
        nodes   — {name: (cx, cy, w, h)}
        edges   — [(src, dst, points, label, lx, ly)]
    """
    nodes = {}
    edges = []
    graph_w = graph_h = 0

    for line in plain.splitlines():
        parts = tokenize_plain(line)
        if not parts:
            continue

        if parts[0] == 'graph':
            graph_w = float(parts[2]) * scale
            graph_h = float(parts[3]) * scale

        elif parts[0] == 'node':
            # node name cx cy w h label style shape color fillcolor
            name  = parts[1]
            cx    = float(parts[2]) * scale
            cy    = float(parts[3]) * scale
            w     = float(parts[4]) * scale
            h     = float(parts[5]) * scale
            nodes[name] = (cx, cy, w, h)

        elif parts[0] == 'edge':
            src   = parts[1]
            dst   = parts[2]
            n_pts = int(parts[3])
            pts   = []
            idx   = 4
            for _ in range(n_pts):
                px = float(parts[idx])   * scale
                py = float(parts[idx+1]) * scale
                pts.append((px, py))
                idx += 2
            # label may follow (quoted string, not a style keyword)
            label = lx = ly = None
            style_keywords = {'solid','dashed','bold','invis','dotted'}
            if idx < len(parts) and parts[idx] not in style_keywords:
                label = parts[idx].replace('\\n', '\n')
                lx    = float(parts[idx+1]) * scale
                ly    = float(parts[idx+2]) * scale
            edges.append((src, dst, pts, label, lx, ly))

    return graph_w, graph_h, nodes, edges


# ── SVG helpers ────────────────────────────────────────────────────────────────
def x(v):   return f'{v:.1f}'
def esc(s): return s.replace('&', '&amp;')


def svg_defs():
    return '''<defs>
  <marker id="arr"       viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5" markerHeight="5" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="#555555"/>
  </marker>
  <marker id="arr-green" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5" markerHeight="5" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="#2d7a45"/>
  </marker>
  <marker id="arr-red"   viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5" markerHeight="5" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/>
  </marker>
</defs>'''


def truncate_text(text: str, max_chars: int = 26) -> str:
    """Truncate text to max_chars, adding ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + '…'


def wrap_text(text: str, max_chars: int = 26) -> str:
    """Word-wrap text at max_chars per line, return lines joined by \\n."""
    words = text.split()
    lines, current, length = [], [], 0
    for word in words:
        cost = len(word) + (1 if current else 0)
        if length + cost > max_chars and current:
            lines.append(' '.join(current))
            current, length = [word], len(word)
        else:
            current.append(word)
            length += cost
    if current:
        lines.append(' '.join(current))
    return '\n'.join(lines)


def svg_text(tx, ty, text, anchor='middle', size=11, weight='normal',
             fill='#222', baseline='auto'):
    lines = text.split('\n')
    if len(lines) == 1:
        return (f'<text x="{x(tx)}" y="{x(ty)}" text-anchor="{anchor}" '
                f'dominant-baseline="{baseline}" '
                f'font-family="{FONT}" font-size="{size}" '
                f'font-weight="{weight}" fill="{fill}">{esc(text)}</text>')
    dy = size * 1.3
    start_y = ty - (len(lines) - 1) * dy / 2
    parts = [f'<text text-anchor="{anchor}" font-family="{FONT}" '
             f'font-size="{size}" font-weight="{weight}" fill="{fill}">']
    for i, ln in enumerate(lines):
        parts.append(f'<tspan x="{x(tx)}" y="{x(start_y + i*dy)}"'
                     f' dominant-baseline="{baseline}">{esc(ln)}</tspan>')
    parts.append('</text>')
    return '\n'.join(parts)


def chem_sub(text: str) -> str:
    """Escape text for SVG and wrap letter+digit sequences as subscript tspans.
    e.g. 'CO2 to air' → 'CO<tspan ...>2</tspan> to air'
    """
    import re
    result = ''
    last = 0
    for m in re.finditer(r'([A-Za-z])(\d+)', text):
        result += esc(text[last:m.start()])
        result += esc(m.group(1))
        result += f'<tspan baseline-shift="sub" font-size="0.75em">{esc(m.group(2))}</tspan>'
        last = m.end()
    result += esc(text[last:])
    return result


def svg_chem_text(tx, ty, text, anchor='middle', size=11, weight='normal',
                  fill='#222', baseline='auto'):
    """Like svg_text but renders chemical subscripts (CO2 → CO₂) via tspan."""
    lines = text.split('\n')
    if len(lines) == 1:
        return (f'<text x="{x(tx)}" y="{x(ty)}" text-anchor="{anchor}" '
                f'dominant-baseline="{baseline}" '
                f'font-family="{FONT}" font-size="{size}" '
                f'font-weight="{weight}" fill="{fill}">{chem_sub(text)}</text>')
    dy = size * 1.3
    start_y = ty - (len(lines) - 1) * dy / 2
    parts = [f'<text text-anchor="{anchor}" font-family="{FONT}" '
             f'font-size="{size}" font-weight="{weight}" fill="{fill}">']
    for i, ln in enumerate(lines):
        parts.append(f'<tspan x="{x(tx)}" y="{x(start_y + i*dy)}"'
                     f' dominant-baseline="{baseline}">{chem_sub(ln)}</tspan>')
    parts.append('</text>')
    return '\n'.join(parts)


def svg_line(x1, y1, x2, y2, color, marker='arr', width=1.6):
    return (f'<line x1="{x(x1)}" y1="{x(y1)}" x2="{x(x2)}" y2="{x(y2)}" '
            f'stroke="{color}" stroke-width="{width}" '
            f'marker-end="url(#{marker})"/>')


def svg_rect(rx, ry, rw, rh, fill, corner=8):
    return (f'<rect x="{x(rx)}" y="{x(ry)}" width="{rw}" height="{rh}" '
            f'rx="{corner}" fill="{fill}"/>')


# ── Elementary flow injection ──────────────────────────────────────────────────
def elementary_flows(recipe: dict, nodes: dict, flip_y: float,
                     show_quantities: bool = True,
                     scaling: dict = {}) -> list[str]:
    """
    Generate SVG elements for biosphere inputs (green, top) and
    emissions (red, bottom) for every process node.
    flip_y: canvas height used to flip graphviz y-axis (dot origin is bottom-left)
    """
    els = []

    for p in recipe['processes']:
        name = p['name']
        if name not in nodes:
            continue
        cx, cy, nw, nh = nodes[name]
        # flip y: graphviz origin is bottom-left, SVG is top-left
        cy = flip_y - cy
        box_top = cy - nh / 2
        box_bot = cy + nh / 2
        proc_scaling = scaling.get(name, 1.0)

        # ── Resources / biosphere inputs (green arrows, from above into top of box) ──
        resources = p.get('resources', [])
        n_res = len(resources)
        res_spacing = (nw * 0.75) / (n_res - 1) if n_res > 1 else EMIT_OFFSET
        for i, res in enumerate(resources):
            rx = cx + (i - (n_res - 1) / 2) * res_spacing
            start_y = box_top - ELEM_ARM
            from_nature_y = start_y - 10

            els.append(svg_text(rx, from_nature_y, 'from Nature',
                                anchor='start', size=9, fill=COL_GREEN, baseline='auto',
                                weight='bold'))
            els.append(svg_line(rx, start_y, rx, box_top,
                                COL_GREEN, marker='arr-green'))
            shaft_mid = start_y + ELEM_ARM * 0.38
            els.append(svg_chem_text(rx - 5, shaft_mid,
                                     _display_name(res['flow']), anchor='end', size=11, fill=COL_GREEN,
                                     weight='bold'))
            if show_quantities:
                scaled_amount = res['amount'] * proc_scaling
                els.append(svg_text(rx - 5, shaft_mid + 14,
                                    f"{scaled_amount:.4g} {_res_unit(recipe, res['flow'])}",
                                    anchor='end', size=11, fill=COL_GREEN,
                                    weight='bold'))

        # ── Emissions (red arrows, exit bottom downward) ──
        emissions = p.get('emissions', [])
        n_em = len(emissions)
        em_spacing = (nw * 0.75) / (n_em - 1) if n_em > 1 else EMIT_OFFSET
        for i, em in enumerate(emissions):
            ex = cx + (i - (n_em - 1) / 2) * em_spacing
            end_y = box_bot + ELEM_ARM
            to_air_y = end_y + 12

            els.append(svg_line(ex, box_bot, ex, end_y,
                                COL_RED, marker='arr-red'))
            mid_y = box_bot + ELEM_ARM * 0.38
            unit = _em_unit(recipe, em['flow'])
            els.append(svg_chem_text(ex - 5, mid_y,
                                     _display_name(em['flow']), anchor='end', size=11, fill=COL_RED,
                                     weight='bold'))
            if show_quantities:
                scaled_amount = em['amount'] * proc_scaling
                els.append(svg_text(ex - 5, mid_y + 14,
                                    f"{scaled_amount:.4g} {unit}", anchor='end', size=11, fill=COL_RED,
                                    weight='bold'))
            els.append(svg_text(ex, to_air_y, 'to Air',
                                anchor='start', size=9, fill=COL_RED, baseline='auto',
                                weight='bold'))

    return els


def background_inputs(recipe: dict, nodes: dict, flip_y: float,
                      show_quantities: bool = True,
                      scaling: dict = {}) -> list[str]:
    """
    Draw background database inputs (database: bafu etc.) as labelled arrows
    entering the left side of the receiving process box.
    """
    els = []
    ARM = 90  # horizontal arm length

    for p in recipe['processes']:
        name = p['name']
        if name not in nodes:
            continue
        cx, cy, nw, nh = nodes[name]
        cy = flip_y - cy
        box_left = cx - nw / 2

        bg_inputs = [inp for inp in p.get('inputs', [])
                     if inp.get('database') and not _producer(recipe, inp['flow'])]
        if not bg_inputs:
            continue

        n = len(bg_inputs)
        spacing = nh * 0.6 / (n - 1) if n > 1 else 0
        proc_scaling = scaling.get(name, 1.0)

        for i, inp in enumerate(bg_inputs):
            iy = cy + (i - (n - 1) / 2) * spacing
            start_x = box_left - ARM
            els.append(svg_line(start_x, iy, box_left, iy, COL_TECH_EDGE))
            mid_x = start_x + ARM * 0.5
            els.append(svg_text(mid_x, iy - 6,
                                _display_name(inp['flow']),
                                anchor='middle', size=10, fill='#444', weight='bold'))
            if show_quantities:
                scaled = inp['amount'] * proc_scaling
                unit = inp.get('unit', '')
                els.append(svg_text(mid_x, iy + 8,
                                    f"{scaled:.4g} {unit}",
                                    anchor='middle', size=10, fill='#444'))

    return els


def _res_unit(recipe, flow_name):
    for f in recipe.get('elementary_flows', {}).get('resources', []):
        if f['name'] == flow_name:
            return f['unit']
    return ''


def _em_unit(recipe, flow_name):
    for f in recipe.get('elementary_flows', {}).get('emissions', []):
        if f['name'] == flow_name:
            return f['unit']
    return ''


# ── Process & FU box rendering ─────────────────────────────────────────────────
def process_boxes(recipe: dict, nodes: dict, flip_y: float,
                  scaling: dict = {},
                  show_quantities: bool = True,
                  bg_nodes: set = set()) -> list[str]:
    els = []

    for name, (cx, cy, nw, nh) in nodes.items():
        cy = flip_y - cy
        is_fu = name == 'Functional Unit'
        is_bg = name in bg_nodes
        fill  = COL_FU if is_fu else (COL_BACKGROUND if is_bg else COL_PROCESS)
        bx    = cx - nw / 2
        by    = cy - nh / 2

        els.append(svg_rect(bx, by, nw, nh, fill))

        if is_fu:
            fu = recipe['functional_unit']
            desc = wrap_text(fu['description'])
            n_desc_lines = len(desc.split('\n'))
            els.append(svg_text(cx, cy - nh * 0.28, 'Functional Unit',
                                size=11, fill='white'))
            els.append(svg_text(cx, cy + nh * (0.05 + 0.07 * (n_desc_lines - 1)),
                                desc, size=10, fill='white'))
        elif is_bg:
            els.append(svg_text(cx, cy, truncate_text(name), size=11, fill='white'))
        else:
            idx = next((i+1 for i, p in enumerate(recipe['processes'])
                        if p['name'] == name), '?')
            els.append(svg_text(cx, cy - 8, name, size=11, fill='white'))
            if show_quantities:
                sc = scaling.get(name, 1.0)
                els.append(svg_text(cx, cy + 8,
                                    f"s{idx} = {sc:.4g}", size=11, fill='white'))

    return els


# ── Technosphere edge rendering ────────────────────────────────────────────────
def tech_edges(edges: list, flip_y: float, recipe: dict,
               nodes: dict, show_quantities: bool = True,
               scaling: dict = {}) -> list[str]:
    """
    Draw edges from source box right-edge to dest box left-edge.
    We ignore dot spline control points (they don't clip to box boundaries
    in -Tplain) and compute the endpoints directly from node positions.
    For diagonal edges (different y), we draw straight lines.
    Label is placed at the midpoint of the line.
    """
    els = []
    ref_proc = recipe['reference_process']
    for src, dst, pts, label, lx, ly in edges:
        if not pts:
            continue
        if src not in nodes or dst not in nodes:
            continue

        scx, scy, snw, snh = nodes[src]
        dcx, dcy, dnw, dnh = nodes[dst]
        scy = flip_y - scy
        dcy = flip_y - dcy

        # start: right edge midpoint of source box
        x1 = scx + snw / 2
        y1 = scy
        # end: left edge midpoint of dest box
        x2 = dcx - dnw / 2
        y2 = dcy

        els.append(svg_line(x1, y1, x2, y2, COL_TECH_EDGE))

        if label:
            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            if show_quantities:
                amount = _edge_amount(recipe, src, dst, label)
                unit   = _flow_unit(recipe, label)
                if amount is not None:
                    dst_scale = scaling.get(dst, 1.0) if dst != 'Functional Unit' else scaling.get(ref_proc, 1.0)
                    scaled = amount * dst_scale
                    lbl = f"{label}\n{scaled:.4g} {unit}"
                    els.append(svg_text(mx, my - 14, lbl,
                                        size=11, fill='#444', baseline='auto',
                                        weight='bold'))
                else:
                    els.append(svg_text(mx, my - 5, label,
                                        size=11, fill='#444', baseline='auto',
                                        weight='bold'))
            else:
                els.append(svg_text(mx, my - 5, label,
                                    size=11, fill='#444', baseline='auto',
                                    weight='bold'))
    return els


def _edge_amount(recipe: dict, src: str, dst: str, flow: str):
    """Return the amount for a technosphere flow between src and dst."""
    # check inputs of dst process
    for p in recipe['processes']:
        if p['name'] == dst:
            for inp in p.get('inputs', []):
                if inp['flow'] == flow:
                    return inp['amount']
    # check functional unit edge (amount for the reference product only)
    if dst == 'Functional Unit':
        return recipe['functional_unit']['amount']
    return None


# ── Unit-process card ─────────────────────────────────────────────────────────
def generate_unit_process(recipe: dict, proc_name: str, out_path: str):
    """Generate a standalone SVG card showing one unit process."""
    proc = _ref_process(recipe, proc_name)

    U_MARGIN  = 30
    H_ARM     = 90     # horizontal arm for inputs / reference output
    V_ARM     = 50     # vertical arm for resources / emissions
    IN_SPACE  = 36     # vertical spacing between stacked inputs

    inputs    = proc.get('inputs', [])
    emissions = proc.get('emissions', [])
    resources = proc.get('resources', [])
    n_in  = len(inputs)
    n_em  = len(emissions)
    n_res = len(resources)

    # Spread arrows across ~75% of box width; fall back to EMIT_OFFSET for single arrows
    em_spacing  = (BOX_W * 0.75) / (n_em  - 1) if n_em  > 1 else EMIT_OFFSET
    res_spacing = (BOX_W * 0.75) / (n_res - 1) if n_res > 1 else EMIT_OFFSET

    # ── Canvas width ──────────────────────────────────────────────────────────
    LLABEL = 110 if n_in else 20   # space to the left of the input arm start
    RLABEL = 20                     # breathing room to the right of output arm end
    canvas_w = U_MARGIN + LLABEL + H_ARM + BOX_W + H_ARM + RLABEL + U_MARGIN

    # ── Box centre x/y ────────────────────────────────────────────────────────
    cx = U_MARGIN + LLABEL + H_ARM + BOX_W / 2

    input_half = max(0.0, (n_in - 1) / 2 * IN_SPACE)
    above = TITLE_HEIGHT + U_MARGIN
    if n_res:
        above += V_ARM + 28   # arrow shaft + "from Nature" label
    above = max(above, TITLE_HEIGHT + U_MARGIN + input_half)
    cy = above + BOX_H / 2

    below = BOX_H / 2 + U_MARGIN
    if n_em:
        below = max(below, BOX_H / 2 + V_ARM + 22)   # arrow shaft + "to Air" label
    below = max(below, BOX_H / 2 + input_half + U_MARGIN)

    canvas_h = cy + below

    parts = []

    # ── Process box ───────────────────────────────────────────────────────────
    bx, by = cx - BOX_W / 2, cy - BOX_H / 2
    parts.append(svg_rect(bx, by, BOX_W, BOX_H, COL_PROCESS))
    parts.append(svg_text(cx, cy, proc_name, fill='white', size=11))

    # ── Reference output (right arrow) ───────────────────────────────────────
    ro  = proc['reference_output']
    x1r = cx + BOX_W / 2
    x2r = x1r + H_ARM
    parts.append(svg_line(x1r, cy, x2r, cy, COL_TECH_EDGE))
    unit = _flow_unit(recipe, ro['flow'])
    parts.append(svg_text((x1r + x2r) / 2, cy - 14,
                          f"{ro['flow']}\n{ro['amount']} {unit}",
                          anchor='middle', size=11, fill='#444', weight='bold'))

    # ── Inputs (left arrows, stacked vertically) ──────────────────────────────
    x2l = cx - BOX_W / 2
    x1l = x2l - H_ARM
    for i, inp in enumerate(inputs):
        y_in = cy + (i - (n_in - 1) / 2) * IN_SPACE
        parts.append(svg_line(x1l, y_in, x2l, y_in, COL_TECH_EDGE))
        u = _flow_unit(recipe, inp['flow'])
        parts.append(svg_text((x1l + x2l) / 2, y_in - 14,
                              f"{truncate_text(inp['flow'])}\n{inp['amount']} {u}",
                              anchor='middle', size=11, fill='#444', weight='bold'))

    # ── Resources (green, entering from above) ────────────────────────────────
    box_top = cy - BOX_H / 2
    for i, res in enumerate(resources):
        off   = (i - (n_res - 1) / 2) * res_spacing
        rx    = cx + off
        y_start = box_top - V_ARM
        parts.append(svg_text(rx, y_start - 14, 'from Nature',
                              anchor='middle', size=9, fill=COL_GREEN, weight='bold'))
        parts.append(svg_line(rx, y_start, rx, box_top, COL_GREEN, marker='arr-green'))
        shaft_mid = y_start + V_ARM * 0.45
        u = _res_unit(recipe, res['flow'])
        parts.append(svg_chem_text(rx - 5, shaft_mid,
                                   _display_name(res['flow']), anchor='end', size=11, fill=COL_GREEN, weight='bold'))
        parts.append(svg_text(rx - 5, shaft_mid + 14,
                              f"{res['amount']} {u}", anchor='end', size=11, fill=COL_GREEN, weight='bold'))

    # ── Emissions (red, exiting below) ────────────────────────────────────────
    box_bot = cy + BOX_H / 2
    for i, em in enumerate(emissions):
        off   = (i - (n_em - 1) / 2) * em_spacing
        ex    = cx + off
        y_end = box_bot + V_ARM
        parts.append(svg_line(ex, box_bot, ex, y_end, COL_RED, marker='arr-red'))
        shaft_mid = box_bot + V_ARM * 0.38
        u = _em_unit(recipe, em['flow'])
        label = _display_name(em['flow'])
        parts.append(svg_chem_text(ex - 5, shaft_mid,
                                   label, anchor='end', size=11, fill=COL_RED, weight='bold'))
        parts.append(svg_text(ex - 5, shaft_mid + 14,
                              f"{em['amount']} {u}", anchor='end', size=11, fill=COL_RED, weight='bold'))
        parts.append(svg_text(ex, y_end + 12, 'to Air',
                              anchor='start', size=9, fill=COL_RED, weight='bold'))

    # ── Title (two lines: process name + "Unit Process" subtitle) ────────────
    title_name = svg_text(canvas_w / 2, 15, proc_name,
                          size=13, fill='#222', weight='bold')
    title_sub  = svg_text(canvas_w / 2, 30, 'Unit Process',
                          size=12, fill='#666')

    svg_out = '\n'.join([
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" '
        f'viewBox="0 0 {canvas_w:.1f} {canvas_h:.1f}">',
        f'<rect x="0" y="0" width="{canvas_w:.1f}" height="{canvas_h:.1f}" fill="#f8f8f8"/>',
        svg_defs(),
        title_name,
        title_sub,
        *parts,
        '</svg>',
    ])
    Path(out_path).write_text(svg_out)
    print(f"Written: {out_path}  ({canvas_w:.0f}×{canvas_h:.0f}px)")


def generate(recipe_path: str, out_path: str, show_quantities: bool = True):
    recipe = load_recipe(recipe_path)

    plain = run_dot_plain(recipe)
    scale = BOX_W / 1.8
    gw, gh, nodes, edges = parse_plain(plain, scale)

    ELEM_PAD = ELEM_ARM + 30

    canvas_w = gw + MARGIN * 2
    offset_x = MARGIN
    offset_y = ELEM_PAD + MARGIN

    shifted_nodes = {
        name: (cx + offset_x, cy + offset_y, nw, nh)
        for name, (cx, cy, nw, nh) in nodes.items()
    }

    flip_y = gh + offset_y

    scaling = compute_scaling(recipe) if show_quantities else {}

    # Collect background input node names for colour differentiation
    fg_names = {p['name'] for p in recipe.get('processes', [])}
    bg_node_names = set()
    for p in recipe.get('processes', []):
        for inp in p.get('inputs', []):
            if inp.get('database') and inp['flow'] not in fg_names:
                bg_node_names.add(inp['flow'])

    svg_parts = []
    svg_parts.append('<!--HEADER-->')
    svg_parts.append('<!--BG-->')
    svg_parts.append(svg_defs())
    svg_parts.append('<!--TITLE-->')

    svg_parts.extend(elementary_flows(recipe, shifted_nodes, flip_y,
                                      show_quantities, scaling))

    shifted_edges = []
    for src, dst, pts, label, lx, ly in edges:
        spts = [(px + offset_x, py + offset_y) for px, py in pts]
        slx  = (lx + offset_x) if lx is not None else None
        sly  = (ly + offset_y) if ly is not None else None
        shifted_edges.append((src, dst, spts, label, slx, sly))

    svg_parts.extend(tech_edges(shifted_edges, flip_y, recipe, shifted_nodes,
                                show_quantities, scaling))
    svg_parts.extend(process_boxes(recipe, shifted_nodes, flip_y, scaling,
                                   show_quantities, bg_nodes=bg_node_names))
    svg_parts.append('</svg>')

    # compute content bounding box in SVG coordinates (post-flip)
    svg_y0 = float('inf')
    svg_y1 = float('-inf')
    for _, (cx, cy, nw, nh) in shifted_nodes.items():
        sc = flip_y - cy
        svg_y0 = min(svg_y0, sc - nh / 2)
        svg_y1 = max(svg_y1, sc + nh / 2)

    for p in recipe['processes']:
        n = shifted_nodes.get(p['name'])
        if not n: continue
        cx, cy, nw, nh = n
        sc = flip_y - cy
        if p.get('resources'):
            svg_y0 = min(svg_y0, sc - nh / 2 - ELEM_ARM - 24)
        if p.get('emissions'):
            svg_y1 = max(svg_y1, sc + nh / 2 + ELEM_ARM + 22)

    # extend bounding box to include title
    title = recipe.get('name', '')
    if title:
        svg_y0 -= TITLE_HEIGHT

    content_h = svg_y1 - svg_y0

    if title:
        title_y = svg_y0 + TITLE_HEIGHT * 0.7
        svg_parts[3] = svg_text(canvas_w / 2, title_y, title,
                                size=14, fill='#222', weight='bold')

    svg_parts[0] = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="100%" '
        f'viewBox="0 {svg_y0:.1f} {canvas_w:.1f} {content_h:.1f}">'
    )
    svg_parts[1] = (
        f'<rect x="0" y="{svg_y0:.1f}" width="{canvas_w:.1f}" '
        f'height="{content_h:.1f}" fill="#f8f8f8"/>'
    )

    out = '\n'.join(svg_parts)
    Path(out_path).write_text(out)
    print(f"Written: {out_path}  ({canvas_w:.0f}×{content_h:.0f}px)")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate an LCA product-system SVG from a product graph.")
    parser.add_argument('recipe', help='Path to product_graph.yaml')
    parser.add_argument('output', nargs='?', default=None,
                        help='Output SVG path (default: same dir as recipe)')
    parser.add_argument('--structure', action='store_true',
                        help='Show structure only (no amounts or scaling factors)')
    parser.add_argument('--scaled', action='store_true',
                        help='Show amounts and scaling factors (default)')
    parser.add_argument('--unit-process', metavar='NAME',
                        help='Generate a standalone card for one unit process by name')
    parser.add_argument('--all-unit-processes', action='store_true',
                        help='Generate one unit-process card SVG per process in the recipe')
    args = parser.parse_args()

    if args.unit_process:
        recipe = load_recipe(args.recipe)
        slug = args.unit_process.split()[0]
        out = args.output or str(Path(args.recipe).parent / f"unit_process_{slug}.svg")
        generate_unit_process(recipe, args.unit_process, out)
    elif args.all_unit_processes:
        recipe = load_recipe(args.recipe)
        base = Path(args.recipe).parent
        for p in recipe['processes']:
            slug = p['name'].split()[0]
            generate_unit_process(recipe, p['name'], str(base / f"unit_process_{slug}.svg"))
    else:
        out_path = args.output or args.recipe.replace('.md', '.svg')
        show_quantities = not args.structure
        generate(args.recipe, out_path, show_quantities=show_quantities)
