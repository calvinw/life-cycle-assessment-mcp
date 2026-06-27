"""
scripts/bafu_graph_svg.py — Generate supply chain SVGs for BAFU background processes.

Uses bw_graph_tools to traverse the supply chain and graphviz dot for layout.

Usage:
    python scripts/bafu_graph_svg.py "Yarn production, cotton fibres" GLO output.svg
    python scripts/bafu_graph_svg.py "Aluminium, production mix, at plant" RER output.svg --depth 3 --cutoff 0.02
"""

import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = pathlib.Path(__file__).parent.parent / "brightway_data"
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

# ── Style ──────────────────────────────────────────────────────────────────────
COL_FU       = "#7b4ea6"   # purple  — functional unit
COL_PROCESS  = "#3a7ebf"   # blue    — process nodes
COL_EDGE     = "#555555"   # dark grey edge
COL_WHITE    = "#ffffff"
COL_LIGHT    = "#f0f4fa"
FONT         = "Helvetica,Arial,sans-serif"
BOX_W, BOX_H = 180, 52


def _short_name(name: str, max_len: int = 30) -> str:
    if len(name) <= max_len:
        return name
    words = name.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_len and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return "\\n".join(lines[:3])


def generate_bafu_svg(
    activity_name: str,
    location: str,
    method: tuple,
    output_path: str,
    max_depth: int = 4,
    cutoff: float = 0.01,
    database: str = "bafu",
    activity=None,          # pass a bw2data Activity directly to bypass name lookup
    functional_unit=None,   # dict {activity: amount} — overrides activity/location lookup
):
    import bw2data as bd
    import bw2calc as bc
    from bw_graph_tools import NewNodeEachVisitGraphTraversal

    bd.projects.set_current(os.environ.get("BRIGHTWAY_PROJECT", "lca_server"))

    if functional_unit is not None:
        act = list(functional_unit.keys())[0]
        fu  = functional_unit
    elif activity is not None:
        act = activity
        fu  = {act: 1}
    else:
        db = bd.Database(database)
        act = next(
            (a for a in db if a["name"] == activity_name and a.get("location") == location),
            None,
        )
        if act is None:
            raise ValueError(f"Process '{activity_name}' [{location}] not found in '{database}'")
        fu = {act: 1}

    lca = bc.LCA(fu, method)
    lca.lci()
    lca.lcia()
    total = lca.score
    method_label = f"{method[1]} ({method[2]})"
    unit = bd.methods[method].get("unit", "")

    result = NewNodeEachVisitGraphTraversal.calculate(lca, cutoff=cutoff, max_depth=max_depth)

    # Build reverse mapping: matrix_index → activity key
    rev = {lca.dicts.activity[k]: k for k in lca.dicts.activity}

    def get_act(matrix_index):
        if matrix_index == -1:
            return None
        key = rev.get(matrix_index)
        if key:
            try:
                return bd.get_node(id=key)
            except Exception:
                pass
        return None

    # Build node label map
    node_labels = {}   # unique_id → dot node id
    node_info   = {}   # unique_id → dict

    for uid, node in result["nodes"].items():
        dot_id = f"n{str(uid).replace('-', '_')}"
        node_labels[uid] = dot_id
        if node.activity_index == -1:
            node_info[uid] = {"name": "Functional Unit", "location": "", "depth": 0,
                               "score": node.cumulative_score, "pct": 100.0, "is_fu": True}
        else:
            a = get_act(node.activity_index)
            name = a["name"] if a else f"idx={node.activity_index}"
            loc  = a.get("location", "") if a else ""
            pct  = node.cumulative_score / total * 100 if total else 0
            node_info[uid] = {"name": name, "location": loc, "depth": node.depth,
                               "score": node.cumulative_score, "pct": pct, "is_fu": False}

    # ── Build DOT source ───────────────────────────────────────────────────────
    dot_lines = [
        "digraph G {",
        '  rankdir=LR;',
        '  bgcolor="white";',
        f'  graph [fontname="{FONT}" pad="0.4" nodesep="0.5" ranksep="0.8"];',
        f'  node  [fontname="{FONT}" shape=box style="filled,rounded" '
        f'fontsize="11" margin="0.15,0.1"];',
        f'  edge  [fontname="{FONT}" fontsize="10" color="{COL_EDGE}" '
        f'arrowsize="0.7"];',
    ]

    # Nodes
    for uid, info in node_info.items():
        dot_id = node_labels[uid]
        name   = _short_name(info["name"])
        loc    = info["location"]
        pct    = info["pct"]
        score  = info["score"]

        if info["is_fu"]:
            label = (f'<<B>Functional Unit</B><BR/>'
                     f'<FONT POINT-SIZE="10">1 × {_short_name(activity_name, 35)}</FONT><BR/>'
                     f'<FONT POINT-SIZE="10"><B>{score:.3f} {unit}</B></FONT>>')
            dot_lines.append(
                f'  {dot_id} [label={label} fillcolor="{COL_FU}" '
                f'fontcolor="white" width="2.2" height="0.7"];'
            )
        else:
            label = (f'<<B>{name}</B>'
                     + (f'<BR/><FONT COLOR="#888888" POINT-SIZE="9">[{loc}]</FONT>' if loc else "")
                     + f'<BR/><FONT POINT-SIZE="10">{score:.3f} {unit} ({pct:.1f}%)</FONT>>')
            fill = COL_LIGHT if info["depth"] > 1 else COL_PROCESS
            fc   = "#333333" if info["depth"] > 1 else "white"
            dot_lines.append(
                f'  {dot_id} [label={label} fillcolor="{fill}" '
                f'fontcolor="{fc}" width="2.4" height="0.7"];'
            )

    # Edges
    for edge in result["edges"]:
        c_uid = edge.consumer_unique_id
        p_uid = edge.producer_unique_id
        if c_uid not in node_labels or p_uid not in node_labels:
            continue
        amt = edge.amount
        dot_lines.append(
            f'  {node_labels[p_uid]} -> {node_labels[c_uid]} '
            f'[label="{amt:.3g}"];'
        )

    # Title
    dot_lines.append(
        f'  labelloc="t"; label="{activity_name} [{location}]\\n'
        f'{method_label}  |  Total: {total:.4f} {unit}";'
        f'  fontsize="13"; fontname="{FONT}";'
    )
    dot_lines.append("}")
    dot_src = "\n".join(dot_lines)

    # ── Render with graphviz dot ───────────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".dot", mode="w", delete=False) as f:
        f.write(dot_src)
        dot_path = f.name

    try:
        result_svg = subprocess.run(
            ["dot", "-Tsvg", dot_path],
            capture_output=True, text=True, check=True
        ).stdout
    finally:
        os.unlink(dot_path)

    pathlib.Path(output_path).write_text(result_svg)
    print(f"Written: {output_path}  (total={total:.4f} {unit})")
    return result_svg


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate supply chain SVG for a BAFU process")
    parser.add_argument("name",     help="Process name (exact)")
    parser.add_argument("location", help="Location code e.g. RER, GLO, CH")
    parser.add_argument("output",   help="Output SVG path")
    parser.add_argument("--depth",  type=int,   default=4,    help="Max traversal depth (default 4)")
    parser.add_argument("--cutoff", type=float, default=0.01, help="Score cutoff fraction (default 0.01)")
    parser.add_argument("--method", default="EF v3.0|climate change|global warming potential (GWP100)",
                        help="Method as pipe-separated tuple")
    parser.add_argument("--database", default="bafu")
    args = parser.parse_args()

    method = tuple(args.method.split("|"))
    generate_bafu_svg(
        activity_name=args.name,
        location=args.location,
        method=method,
        output_path=args.output,
        max_depth=args.depth,
        cutoff=args.cutoff,
        database=args.database,
    )
