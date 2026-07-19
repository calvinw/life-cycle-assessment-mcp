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

    def test_every_mcp_tool_has_a_registered_rest_equivalent(self):
        tree = ast.parse((ROOT / "lca_server.py").read_text())
        rest_tool_routes = None
        mcp_tools = set()
        custom_routes = set()

        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "REST_TOOL_ROUTES"
                for target in node.targets
            ):
                rest_tool_routes = ast.literal_eval(node.value)
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                function = decorator.func
                if not (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "mcp"
                ):
                    continue
                if function.attr == "tool":
                    mcp_tools.add(node.name)
                elif function.attr == "custom_route":
                    route = ast.literal_eval(decorator.args[0])
                    methods = next(
                        ast.literal_eval(keyword.value)
                        for keyword in decorator.keywords
                        if keyword.arg == "methods"
                    )
                    custom_routes.update((method, route) for method in methods)

        self.assertIsNotNone(rest_tool_routes)
        self.assertEqual(mcp_tools, set(rest_tool_routes))
        for route in rest_tool_routes.values():
            self.assertIn((route["method"], route["path"]), custom_routes)


if __name__ == "__main__":
    unittest.main()
