import asyncio
import json
import math
import pathlib
import unittest
from concurrent.futures import ThreadPoolExecutor

from lca_core import LCAEngine
from lca_core import engine as core_engine

import bw2data as bd


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ExtendedLcaResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.polyester_yaml = (ROOT / "case_studies/polyester_tshirt.yaml").read_text()
        cls.cotton_yaml = (ROOT / "case_studies/cotton_fiber.yaml").read_text()
        cls.polyester = cls.engine.run(cls.polyester_yaml)

    def test_existing_fields_and_versioned_extensions_are_present(self):
        expected = {
            "name",
            "method",
            "functional_unit",
            "lci",
            "lcia",
            "scaling_vector",
            "result_schema_version",
            "process_contributions",
            "sankey",
        }
        self.assertTrue(expected.issubset(self.polyester))
        self.assertEqual(self.polyester["result_schema_version"], 2)

    def test_contributions_cover_every_category_and_reconcile(self):
        categories = self.polyester["process_contributions"]["categories"]
        self.assertEqual(
            [category["label"] for category in categories],
            list(self.polyester["lcia"]),
        )
        process_names = [
            "P1 — Oil extraction",
            "P2 — Polyester fiber production",
            "P3 — T-shirt assembly",
        ]
        for category in categories:
            impact = self.polyester["lcia"][category["label"]]
            self.assertEqual(category["unit"], impact["unit"])
            self.assertEqual(category["total_score"], impact["score"])
            self.assertEqual(
                [row["process_name"] for row in category["processes"]],
                process_names,
            )
            reconciled = (
                sum(row["direct_score"] for row in category["processes"])
                + category["residual_score"]
            )
            self.assertTrue(
                math.isclose(
                    reconciled,
                    category["total_score"],
                    rel_tol=core_engine.NUMERIC_REL_TOLERANCE,
                    abs_tol=core_engine.NUMERIC_ABS_TOLERANCE,
                )
            )

    def test_zero_total_categories_use_null_percentages(self):
        category = next(
            item
            for item in self.polyester["process_contributions"]["categories"]
            if item["total_score"] == 0
        )
        self.assertTrue(
            all(row["percentage"] is None for row in category["processes"])
        )

    def test_sankey_uses_solved_scaling_vector_once(self):
        links = self.polyester["sankey"]["links"]

        def amount(kind, flow):
            return next(
                link["amount"]
                for link in links
                if link["kind"] == kind and link["flow_name"] == flow
            )

        scaling = self.polyester["scaling_vector"]
        self.assertAlmostEqual(
            amount("technosphere", "Crude oil"),
            1.5 * scaling["P2 — Polyester fiber production"],
        )
        self.assertAlmostEqual(
            amount("technosphere", "Polyester fiber"),
            0.2 * scaling["P3 — T-shirt assembly"],
        )
        self.assertAlmostEqual(amount("final_product", "T-shirt"), 1.0)
        self.assertEqual(
            self.polyester["sankey"]["available_units"], ["kg", "unit"]
        )

    def test_sankey_endpoints_and_ids_are_complete_and_unique(self):
        sankey = self.polyester["sankey"]
        node_ids = [node["id"] for node in sankey["nodes"]]
        link_ids = [link["id"] for link in sankey["links"]]
        self.assertEqual(len(node_ids), len(set(node_ids)))
        self.assertEqual(len(link_ids), len(set(link_ids)))
        for link in sankey["links"]:
            self.assertIn(link["source"], node_ids)
            self.assertIn(link["target"], node_ids)

        contribution_ids = {
            row["process_id"]
            for category in self.polyester["process_contributions"]["categories"]
            for row in category["processes"]
        }
        sankey_process_ids = {
            node["id"]
            for node in sankey["nodes"]
            if node["kind"] == "process" and node.get("scope") == "foreground"
        }
        self.assertEqual(contribution_ids, sankey_process_ids)

    def test_result_numbers_are_finite(self):
        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    yield from walk(item)
            elif isinstance(value, list):
                for item in value:
                    yield from walk(item)
            elif isinstance(value, float):
                yield value

        self.assertTrue(all(math.isfinite(value) for value in walk(self.polyester)))

    def test_ids_and_order_are_deterministic(self):
        repeated = self.engine.run(self.polyester_yaml)
        self.assertEqual(
            repeated["process_contributions"], self.polyester["process_contributions"]
        )
        self.assertEqual(repeated["sankey"], self.polyester["sankey"])

    def test_temporary_foreground_is_removed_after_success_and_failure(self):
        self.assertFalse(
            any(
                name.startswith(core_engine.FOREGROUND_DB_PREFIX)
                for name in bd.databases
            )
        )
        invalid_method = self.polyester_yaml.replace(
            'method_name: "TRACI v2.1"', 'method_name: "missing method"'
        )
        with self.assertRaisesRegex(ValueError, "not found"):
            self.engine.run(invalid_method)
        self.assertFalse(
            any(
                name.startswith(core_engine.FOREGROUND_DB_PREFIX)
                for name in bd.databases
            )
        )

    def test_duplicate_process_identity_is_rejected(self):
        duplicate = self.polyester_yaml.replace(
            "P2 — Polyester fiber production", "P1 — Oil extraction"
        )
        with self.assertRaisesRegex(ValueError, "Duplicate process name"):
            self.engine.run(duplicate)

    def test_concurrent_requests_do_not_cross_contaminate(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            polyester_future = pool.submit(self.engine.run, self.polyester_yaml)
            cotton_future = pool.submit(self.engine.run, self.cotton_yaml)
            polyester = polyester_future.result(timeout=30)
            cotton = cotton_future.result(timeout=30)

        self.assertEqual(polyester["name"], "Polyester T-shirt — 1 unit")
        self.assertEqual(cotton["name"], "Cotton Fiber — 1 kg")
        polyester_processes = set(polyester["scaling_vector"])
        cotton_processes = set(cotton["scaling_vector"])
        self.assertTrue(polyester_processes.isdisjoint(cotton_processes))
        self.assertFalse(
            any(
                name.startswith(core_engine.FOREGROUND_DB_PREFIX)
                for name in bd.databases
            )
        )

    def test_background_processes_are_explicit_in_sankey_and_impact_is_residual(self):
        source = (ROOT / "bafu_examples/plastic_broom.yaml").read_text()
        result = self.engine.run(source)
        background_nodes = [
            node
            for node in result["sankey"]["nodes"]
            if node.get("scope") == "background"
        ]
        self.assertEqual(len(background_nodes), 3)
        self.assertTrue(
            all(node["id"].startswith("background-process:") for node in background_nodes)
        )
        climate = next(
            category
            for category in result["process_contributions"]["categories"]
            if "climate change" in category["label"]
        )
        self.assertNotEqual(climate["residual_score"], 0)

    def test_mcp_discovery_exposes_nested_result_schema(self):
        import lca_server

        async def get_schema():
            tools = await lca_server.mcp.list_tools()
            return next(tool.output_schema for tool in tools if tool.name == "run_lca")

        schema = asyncio.run(get_schema())
        self.assertEqual(
            schema["properties"]["result_schema_version"]["const"], 2
        )
        self.assertIn("process_contributions", schema["properties"])
        self.assertIn("sankey", schema["properties"])
        self.assertIn("svg_scaled", schema["properties"])
        self.assertIn("svg_structure", schema["properties"])

    def test_official_jacket_bundle_matches_yaml_and_contains_visuals(self):
        yaml_text = (ROOT / "case_studies/jacket.yaml").read_text()
        bundle = json.loads((ROOT / "case_studies/jacket.json").read_text())
        self.assertEqual(bundle["product_graph"], yaml_text)
        self.assertTrue(bundle["svg_structure"].startswith("<svg"))
        self.assertTrue(bundle["svg_scaled"].startswith("<svg"))
        self.assertEqual(
            list(bundle["unit_process_svgs"]),
            [
                "P0 — Raw material extraction",
                "P1 — Spinning",
                "P2 — Fabric weaving",
                "P3 — Zipper production",
                "P4 — Jacket assembly",
            ],
        )


if __name__ == "__main__":
    unittest.main()
