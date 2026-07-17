import ast
import pathlib
import unittest
from unittest.mock import patch

from lca_core import LCAEngine


ROOT = pathlib.Path(__file__).resolve().parents[1]


class LCAEngineApiTests(unittest.TestCase):
    def test_run_delegates_to_calculation_engine(self):
        engine = LCAEngine()
        result = {"lcia": {"climate change": 1.25}}

        with patch("lca_core.api._engine.run_analysis", return_value=result) as run:
            self.assertIs(engine.run("name: example"), result)

        run.assert_called_once_with("name: example")

    def test_visuals_are_an_explicit_facade_option(self):
        engine = LCAEngine()
        with (
            patch("lca_core.api._engine.run_analysis", return_value={}) as run,
            patch("lca_core.api.generate_svg", side_effect=["scaled", "structure"]) as svg,
        ):
            result = engine.run("name: example", include_visuals=True)

        run.assert_called_once_with("name: example")
        self.assertEqual(result["svg_scaled"], "scaled")
        self.assertEqual(result["svg_structure"], "structure")
        self.assertEqual(
            svg.call_args_list[0].args,
            ("name: example", "scaled"),
        )

    def test_jsonld_import_delegates_to_core_importer(self):
        engine = LCAEngine()
        imported = {"project": "mock", "database": "fixture"}
        with patch("lca_core.api.import_jsonld", return_value=imported) as importer:
            result = engine.import_jsonld(
                "fixture.zip",
                "fixture",
                project="mock",
                replace_project_data=True,
            )

        self.assertIs(result, imported)
        importer.assert_called_once_with(
            "fixture.zip",
            "fixture",
            "mock",
            replace_project_data=True,
        )

    def test_imported_activity_calculation_delegates_to_core_calculator(self):
        engine = LCAEngine()
        calculated = {"score": 42.0, "unit": "kg CO2-Eq"}
        with patch(
            "lca_core.api.calculate_activity", return_value=calculated
        ) as calculate:
            result = engine.calculate_imported_activity(
                "fixture",
                "TRACI 2.1",
                "global warming",
                project="mock",
                product_name="Jacket",
                amount=2,
            )

        self.assertIs(result, calculated)
        calculate.assert_called_once_with(
            "fixture",
            "TRACI 2.1",
            "global warming",
            project="mock",
            amount=2,
            product_name="Jacket",
            code=None,
            location=None,
            activity_type="product",
        )

    def test_core_package_does_not_import_transport_frameworks(self):
        forbidden = {"fastapi", "fastmcp", "starlette", "uvicorn"}
        imported = set()
        for path in (ROOT / "lca_core").glob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])

        self.assertFalse(imported & forbidden)

    def test_mcp_adapter_has_no_direct_brightway_import(self):
        tree = ast.parse((ROOT / "lca_server.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        self.assertFalse(imported & {"bw2calc", "bw2data"})
        self.assertIn("lca_core", imported)


if __name__ == "__main__":
    unittest.main()
