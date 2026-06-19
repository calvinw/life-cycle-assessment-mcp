"""
lca_svg_engine.py — SVG generation for the Life Cycle Assessment MCP.

Wraps lca_svg.generate() and lca_svg.generate_unit_process().
"""

import os
import re
import tempfile
import pathlib
import yaml

from lca_svg import generate as _generate
from lca_svg import generate_unit_process as _generate_unit_process


def _parse_recipe(yaml_text: str) -> dict:
    """Extract and parse YAML frontmatter from a recipe card string."""
    m = re.search(r'^---\n(.*?)^---', yaml_text, re.DOTALL | re.MULTILINE)
    if m:
        return yaml.safe_load(m.group(1))
    return yaml.safe_load(yaml_text)


def _normalise(recipe_card_yaml: str) -> str:
    """Ensure the YAML string has --- fences so lca_svg can parse it."""
    text = recipe_card_yaml.strip()
    if not text.startswith("---"):
        text = f"---\n{text}\n---\n"
    return text


def generate_svg(recipe_card_yaml: str, graph_type: str = "scaled") -> str:
    """
    Generate a full supply chain SVG from a recipe card YAML string.
    graph_type: "scaled" (amounts + scaling factors) or "structure" (flow names only)
    Returns SVG as a string. Does not require the gdt-server.
    """
    show_quantities = graph_type != "structure"
    yaml_text = _normalise(recipe_card_yaml)

    with tempfile.TemporaryDirectory() as tmp:
        recipe_path = os.path.join(tmp, "recipe_card.md")
        out_path    = os.path.join(tmp, "graph.svg")
        pathlib.Path(recipe_path).write_text(yaml_text)
        _generate(recipe_path, out_path, show_quantities=show_quantities)
        return pathlib.Path(out_path).read_text()


def generate_unit_process_svg(recipe_card_yaml: str, process_name: str) -> str:
    """
    Generate a unit process card SVG for one named process.
    process_name must match a process name in the recipe card exactly.
    Returns SVG as a string. Does not require the gdt-server.
    """
    recipe = _parse_recipe(recipe_card_yaml)

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "unit_process.svg")
        _generate_unit_process(recipe, process_name, out_path)
        return pathlib.Path(out_path).read_text()
