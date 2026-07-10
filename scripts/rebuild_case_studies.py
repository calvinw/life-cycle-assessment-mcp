"""
scripts/rebuild_case_studies.py — Regenerate all case study JSON bundles.

Reads each case_studies/*.yaml, runs SVG generation,
and writes the result back to case_studies/*.json.
LCA results are not pre-computed — call run_lca() with the product graph to compute them.

Run after any change to lca_svg_engine or the product graphs:
    uv run python scripts/rebuild_case_studies.py
"""

import os
import json
import pathlib
import sys

# Must be set before bw2data is imported
if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = pathlib.Path(__file__).parent.parent / "brightway_data"
    _bw_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

CASE_STUDIES_DIR = pathlib.Path(__file__).parent.parent / "case_studies"

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from lca_svg_engine import generate_svg, generate_unit_process_svg


def _process_names_from_spec(spec: dict) -> list[str]:
    return [p["name"] for p in spec.get("processes", [])]


def rebuild(yaml_path: pathlib.Path):
    name = yaml_path.stem
    product_graph = yaml_path.read_text()

    print(f"  Generating SVGs...")
    svg_scaled    = generate_svg(product_graph, "scaled")
    svg_structure = generate_svg(product_graph, "structure")

    import yaml
    spec = yaml.safe_load(product_graph)

    unit_process_svgs = {}
    for proc_name in _process_names_from_spec(spec):
        unit_process_svgs[proc_name] = generate_unit_process_svg(product_graph, proc_name)

    bundle = {
        "product_graph": product_graph,
        "svg_structure": svg_structure,
        "svg_scaled": svg_scaled,
        "unit_process_svgs": unit_process_svgs,
    }

    out_path = yaml_path.with_suffix(".json")
    out_path.write_text(json.dumps(bundle, indent=2))
    print(f"  Wrote {out_path.name}")


def main():
    import bw2data as bd
    project = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
    bd.projects.set_current(project)
    print(f"Brightway project: {project}")

    yaml_files = sorted(CASE_STUDIES_DIR.glob("*.yaml"))
    if not yaml_files:
        print("No .yaml files found in case_studies/")
        return

    for yaml_path in yaml_files:
        print(f"\n{yaml_path.name}")
        try:
            rebuild(yaml_path)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
