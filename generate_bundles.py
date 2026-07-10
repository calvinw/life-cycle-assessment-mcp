"""
generate_bundles.py — Pre-compute case study bundles for the LCA MCP server.

For each product graph in case_studies/*.yaml, generates:
  - svg_structure  : supply chain diagram (flow names only)
  - svg_scaled     : supply chain diagram (with amounts and scaling factors)
  - unit_process_svgs : one SVG per process

Saves each bundle as case_studies/<name>.json.
LCA results are not pre-computed — run run_lca() against the product graph instead.

Run once whenever a product graph changes or the engine changes:
    python3 generate_bundles.py
"""

import json
import pathlib
import sys
import yaml
import os

os.environ.setdefault("BRIGHTWAY2_DIR", str(pathlib.Path(__file__).parent / "brightway_data"))

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lca_svg_engine import generate_svg, generate_unit_process_svg

CASE_STUDIES_DIR = pathlib.Path(__file__).parent / "case_studies"


def _parse_process_names(product_graph_text: str) -> list[str]:
    data = yaml.safe_load(product_graph_text)
    return [p["name"] for p in data.get("processes", [])]


def generate_bundle(name: str) -> None:
    product_graph_path = CASE_STUDIES_DIR / f"{name}.yaml"
    product_graph = product_graph_path.read_text()

    print(f"\n[{name}]")

    print("  generating svg_structure ...")
    svg_structure = generate_svg(product_graph, "structure")

    print("  generating svg_scaled ...")
    svg_scaled = generate_svg(product_graph, "scaled")

    process_names = _parse_process_names(product_graph)
    unit_process_svgs: dict[str, str] = {}
    for pname in process_names:
        print(f"  generating unit process svg: {pname} ...")
        unit_process_svgs[pname] = generate_unit_process_svg(product_graph, pname)

    bundle = {
        "product_graph":       product_graph,
        "svg_structure":     svg_structure,
        "svg_scaled":        svg_scaled,
        "unit_process_svgs": unit_process_svgs,
    }

    out_path = CASE_STUDIES_DIR / f"{name}.json"
    out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    print(f"  saved -> {out_path.name} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    yaml_files = sorted(CASE_STUDIES_DIR.glob("*.yaml"))
    if not yaml_files:
        print("No .yaml files found in case_studies/")
        sys.exit(1)

    print(f"Found {len(yaml_files)} case study file(s): {[f.stem for f in yaml_files]}")

    for yaml_file in yaml_files:
        generate_bundle(yaml_file.stem)

    print("\nAll bundles generated.")
