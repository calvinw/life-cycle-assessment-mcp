"""
scripts/rebuild_case_studies.py — Regenerate all case study JSON bundles.

Reads each case_studies/*.md, runs the full LCA + SVG generation,
and writes the result back to case_studies/*.json.

Run after any change to lca_engine, lca_svg_engine, or the biosphere/LCIA data:
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
from lca_engine import run_analysis
from lca_svg_engine import generate_svg, generate_unit_process_svg


def _process_names_from_spec(spec: dict) -> list[str]:
    return [p["name"] for p in spec.get("processes", [])]


def rebuild(md_path: pathlib.Path):
    name = md_path.stem
    recipe_card = md_path.read_text()

    print(f"  Running LCA for {name}...")
    result = run_analysis(recipe_card)

    print(f"  Generating SVGs...")
    svg_scaled    = generate_svg(recipe_card, "scaled")
    svg_structure = generate_svg(recipe_card, "structure")

    import yaml
    text = recipe_card.strip()
    if text.startswith("---"):
        _, fm, _ = text.split("---", 2)
        spec = yaml.safe_load(fm)
    else:
        spec = yaml.safe_load(text)

    unit_process_svgs = {}
    for proc_name in _process_names_from_spec(spec):
        unit_process_svgs[proc_name] = generate_unit_process_svg(recipe_card, proc_name)

    bundle = {
        "recipe_card": recipe_card,
        "svg_structure": svg_structure,
        "svg_scaled": svg_scaled,
        "unit_process_svgs": unit_process_svgs,
        "lca_results": result,
    }

    out_path = md_path.with_suffix(".json")
    out_path.write_text(json.dumps(bundle, indent=2))
    gwp = result['lcia'].get('global warming potential (GWP100)', result['lcia'].get('Global warming', {})).get('score', '?')
    print(f"  Wrote {out_path.name}  (global warming: {gwp})")


def main():
    import bw2data as bd
    project = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
    bd.projects.set_current(project)
    print(f"Brightway project: {project}")

    md_files = sorted(CASE_STUDIES_DIR.glob("*.md"))
    if not md_files:
        print("No .md files found in case_studies/")
        return

    for md_path in md_files:
        print(f"\n{md_path.name}")
        try:
            rebuild(md_path)
        except Exception as exc:
            print(f"  ERROR: {exc}")

    print("\nDone.")


if __name__ == "__main__":
    main()
