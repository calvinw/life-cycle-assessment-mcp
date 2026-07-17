"""Public, transport-independent API for the Python LCA engine."""

from __future__ import annotations

import pathlib
import tempfile
from typing import Any

from . import engine as _engine
from . import search as _search
from .background_svg import generate_bafu_svg
from .imported_activity import calculate_activity
from .jsonld import import_jsonld
from .visualization import generate_svg, generate_unit_process_svg


class LCAEngine:
    """Reusable facade over calculation, search, and visualization services.

    Configuration is read from ``BRIGHTWAY2_DIR`` and ``BRIGHTWAY_PROJECT``
    before this package is imported. No MCP or HTTP dependency is required.
    """

    @property
    def project(self) -> str:
        return _engine.BRIGHTWAY_PROJECT

    def ensure_ready(self) -> None:
        _engine._ensure_databases()

    def run(self, product_graph: str, include_visuals: bool = False) -> dict[str, Any]:
        result = _engine.run_analysis(product_graph)
        if include_visuals:
            result["svg_scaled"] = generate_svg(product_graph, "scaled")
            result["svg_structure"] = generate_svg(product_graph, "structure")
        return result

    def import_jsonld(
        self,
        source: str | pathlib.Path,
        database: str,
        *,
        project: str,
        replace_project_data: bool = False,
    ) -> dict[str, Any]:
        """Import an openLCA JSON-LD directory or ZIP into Brightway."""
        return import_jsonld(
            source,
            database,
            project,
            replace_project_data=replace_project_data,
        )

    def calculate_imported_activity(
        self,
        database: str,
        method_name: str,
        impact_category: str,
        *,
        project: str,
        amount: float = 1.0,
        product_name: str | None = None,
        code: str | None = None,
        location: str | None = None,
        activity_type: str | None = "product",
    ) -> dict[str, Any]:
        """Calculate an activity already imported into a Brightway project."""
        return calculate_activity(
            database,
            method_name,
            impact_category,
            project=project,
            amount=amount,
            product_name=product_name,
            code=code,
            location=location,
            activity_type=activity_type,
        )

    def contributions(
        self, product_graph: str, method_name: str, top_n: int = 10
    ) -> dict[str, Any]:
        return _engine.get_contributions(product_graph, method_name, top_n=top_n)

    def top_emissions(
        self, product_graph: str, method_name: str, top_n: int = 15
    ) -> list[dict[str, Any]]:
        return _engine.top_emissions(product_graph, method_name, top_n=top_n)

    def compare_activities(
        self,
        activity_names: list[str],
        method_name: str,
        database: str = "bafu",
        location: str | None = None,
        amount: float = 1.0,
        method_family: str = "EF v3.1",
    ) -> list[dict[str, Any]]:
        return _engine.compare_activities(
            activity_names,
            method_name,
            database=database,
            location=location,
            amount=amount,
            method_family=method_family,
        )

    def list_methods(self) -> list[dict[str, Any]]:
        return _engine.list_methods()

    def list_databases(self) -> list[dict[str, Any]]:
        return _engine.list_databases()

    def search_activities(
        self, query: str, database: str = "biosphere3", limit: int = 25
    ) -> list[dict[str, Any]]:
        return _engine.search_database(query, database=database, limit=limit)

    def get_activity_inputs(
        self,
        database: str,
        code: str,
        exchange_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self.ensure_ready()
        return _search.get_activity_inputs(
            database,
            code,
            exchange_type=exchange_type,
            limit=limit,
            project=self.project,
        )

    def query_database(self, sql: str, limit: int = 100) -> dict[str, Any]:
        return _engine.query_database(sql, limit=limit)

    def get_database_schema(self) -> dict[str, Any]:
        return _engine.get_database_schema()

    def generate_svg(self, product_graph: str, graph_type: str = "scaled") -> str:
        return generate_svg(product_graph, graph_type)

    def generate_unit_process_svg(self, product_graph: str, process_name: str) -> str:
        return generate_unit_process_svg(product_graph, process_name)

    def generate_background_svg(
        self,
        activity_name: str,
        location: str,
        method_name: str = "EF v3.1",
        method_category: str = "climate change",
        max_depth: int = 4,
        cutoff: float = 0.01,
        database: str = "bafu",
    ) -> str:
        self.ensure_ready()
        import bw2data as bd

        bd.projects.set_current(self.project)
        matches = [
            method
            for method in bd.methods
            if method[0] == method_name
            and method_category.lower() in method[1].lower()
        ]
        if not matches:
            raise ValueError(
                f"No method found for '{method_name}' / '{method_category}'. "
                "Use list_methods() to browse available methods."
            )

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as stream:
            output = pathlib.Path(stream.name)
        try:
            generate_bafu_svg(
                activity_name=activity_name,
                location=location,
                method=matches[0],
                output_path=str(output),
                max_depth=max_depth,
                cutoff=cutoff,
                database=database,
            )
            return output.read_text()
        finally:
            output.unlink(missing_ok=True)

    def check(self) -> dict[str, Any]:
        return _engine.check_brightway()
