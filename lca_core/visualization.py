"""SVG generation for product graphs, independent of MCP transports."""

import os
import re
import tempfile
import pathlib
import yaml

from .svg_renderer import generate as _generate
from .svg_renderer import generate_unit_process as _generate_unit_process


def _parse_recipe(yaml_text: str) -> dict:
    """Parse a product graph YAML string."""
    m = re.search(r'^---\n(.*?)^---', yaml_text, re.DOTALL | re.MULTILINE)
    if m:
        return yaml.safe_load(m.group(1))
    return yaml.safe_load(yaml_text)


def _normalise(product_graph_yaml: str) -> str:
    """Ensure the YAML string has --- fences so lca_svg can parse it."""
    text = product_graph_yaml.strip()
    if not text.startswith("---"):
        text = f"---\n{text}\n---\n"
    return text


def generate_svg(product_graph_yaml: str, graph_type: str = "scaled") -> str:
    """
    Generate a full supply chain SVG from a product graph YAML string.
    graph_type: "scaled" (amounts + scaling factors) or "structure" (flow names only)
    Returns SVG as a string. Does not require the gdt-server.
    """
    show_quantities = graph_type != "structure"
    yaml_text = _normalise(product_graph_yaml)

    with tempfile.TemporaryDirectory() as tmp:
        recipe_path = os.path.join(tmp, "product_graph.yaml")
        out_path    = os.path.join(tmp, "graph.svg")
        pathlib.Path(recipe_path).write_text(yaml_text)
        _generate(recipe_path, out_path, show_quantities=show_quantities)
        return pathlib.Path(out_path).read_text()


def generate_unit_process_svg(product_graph_yaml: str, process_name: str) -> str:
    """
    Generate a unit process card SVG for one named process.
    process_name must match a process name in the product graph exactly.
    Returns SVG as a string. Does not require the gdt-server.
    """
    recipe = _parse_recipe(product_graph_yaml)

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "unit_process.svg")
        _generate_unit_process(recipe, process_name, out_path)
        return pathlib.Path(out_path).read_text()
