"""
generate_bundles.py — Pre-compute case study bundles for the LCA MCP server.

For each recipe card in case_studies/*.md, generates:
  - svg_structure  : supply chain diagram (flow names only)
  - svg_scaled     : supply chain diagram (with amounts and scaling factors)
  - unit_process_svgs : one SVG per process
  - lca_results    : lci, lcia, scaling_vector

Saves each bundle as case_studies/<name>.json.

Run once whenever a recipe card changes or the engine changes:
    python3 generate_bundles.py
"""

import json
import pathlib
import sys
import yaml
import re
import os

os.environ.setdefault("BRIGHTWAY2_DIR", str(pathlib.Path(__file__).parent / "brightway_data"))

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lca_svg_engine import generate_svg, generate_unit_process_svg
from lca_engine import run_analysis

CASE_STUDIES_DIR = pathlib.Path(__file__).parent / "case_studies"


def _parse_process_names(recipe_card_text: str) -> list[str]:
    m = re.search(r'^---\n(.*?)^---', recipe_card_text, re.DOTALL | re.MULTILINE)
    data = yaml.safe_load(m.group(1)) if m else yaml.safe_load(recipe_card_text)
    return [p["name"] for p in data.get("processes", [])]


def generate_bundle(name: str) -> None:
    recipe_card_path = CASE_STUDIES_DIR / f"{name}.md"
    recipe_card = recipe_card_path.read_text()

    print(f"\n[{name}]")

    print("  generating svg_structure ...")
    svg_structure = generate_svg(recipe_card, "structure")

    print("  generating svg_scaled ...")
    svg_scaled = generate_svg(recipe_card, "scaled")

    process_names = _parse_process_names(recipe_card)
    unit_process_svgs: dict[str, str] = {}
    for pname in process_names:
        print(f"  generating unit process svg: {pname} ...")
        unit_process_svgs[pname] = generate_unit_process_svg(recipe_card, pname)

    print("  running lca analysis ...")
    lca_results = run_analysis(recipe_card)
    lca_results.pop("system_id", None)

    bundle = {
        "recipe_card":       recipe_card,
        "svg_structure":     svg_structure,
        "svg_scaled":        svg_scaled,
        "unit_process_svgs": unit_process_svgs,
        "lca_results":       lca_results,
    }

    out_path = CASE_STUDIES_DIR / f"{name}.json"
    out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    print(f"  saved -> {out_path.name} ({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    md_files = sorted(CASE_STUDIES_DIR.glob("*.md"))
    if not md_files:
        print("No .md files found in case_studies/")
        sys.exit(1)

    print(f"Found {len(md_files)} case study file(s): {[f.stem for f in md_files]}")

    for md_file in md_files:
        generate_bundle(md_file.stem)

    print("\nAll bundles generated.")
