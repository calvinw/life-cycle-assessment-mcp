import json
import math
import pathlib
import unittest
from unittest import mock

from lca_core import LCAEngine
from lca_core import engine as core_engine
from lca_core.mock_database import DATABASE_NAME, ensure_mock_background_database

import bw2data as bd


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MockBackgroundDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()
        bd.projects.set_current(core_engine.BRIGHTWAY_PROJECT)

    def test_installer_is_idempotent_and_database_has_four_processes(self):
        status = ensure_mock_background_database(bd)
        self.assertFalse(status["changed"])
        self.assertEqual(status["activities"], 4)
        self.assertEqual(len(bd.Database(DATABASE_NAME)), 4)

    def test_mock_database_is_searchable_through_public_api(self):
        results = self.engine.search_activities(
            "polypropylene", database=DATABASE_NAME
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], [DATABASE_NAME, "mock-polypropylene"])

    def test_mock_background_examples_calculate(self):
        storage = self.engine.run(
            (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        )
        broom = self.engine.run(
            (ROOT / "mock_examples/mock_plastic_broom.yaml").read_text()
        )
        simple_broom = self.engine.run(
            (ROOT / "mock_examples/mock_plastic_broom_simple.yaml").read_text()
        )

        storage_background = [
            node for node in storage["sankey"]["nodes"]
            if node.get("scope") == "background"
        ]
        broom_background = [
            node for node in broom["sankey"]["nodes"]
            if node.get("scope") == "background"
        ]
        simple_broom_background = [
            node for node in simple_broom["sankey"]["nodes"]
            if node.get("scope") == "background"
        ]
        self.assertEqual(len(storage_background), 1)
        self.assertEqual(len(broom_background), 2)
        self.assertEqual(len(simple_broom_background), 2)
        storage_climate = next(
            result["score"]
            for label, result in storage["lcia"].items()
            if label == "climate change | global warming potential (GWP100)"
        )
        broom_climate = next(
            result["score"]
            for label, result in broom["lcia"].items()
            if label == "climate change | global warming potential (GWP100)"
        )
        simple_broom_climate = next(
            result["score"]
            for label, result in simple_broom["lcia"].items()
            if label == "climate change | global warming potential (GWP100)"
        )
        self.assertAlmostEqual(storage_climate, 1.44, places=6)
        self.assertAlmostEqual(broom_climate, 0.948871, places=6)
        self.assertAlmostEqual(simple_broom_climate, 0.945495, places=6)
        self.assertFalse(
            any(
                name.startswith(core_engine.FOREGROUND_DB_PREFIX)
                for name in bd.databases
            )
        )

    def test_bundled_mock_examples_match_their_yaml(self):
        for name in (
            "mock_plastic_broom",
            "mock_plastic_broom_simple",
            "mock_storage_bin",
        ):
            yaml_text = (ROOT / "mock_examples" / f"{name}.yaml").read_text()
            bundle = json.loads(
                (ROOT / "mock_examples" / f"{name}.json").read_text()
            )
            self.assertEqual(bundle["product_graph"], yaml_text)
            self.assertTrue(bundle["svg_structure"].startswith("<svg"))
            self.assertTrue(bundle["svg_scaled"].startswith("<svg"))
            self.assertTrue(bundle["unit_process_svgs"])

    def test_direct_only_freight_is_a_leaf_and_simple_broom_visits_grid_once(self):
        freight = bd.get_node(
            database=DATABASE_NAME,
            code="mock-small-truck-direct",
        )
        self.assertEqual(list(freight.technosphere()), [])

        source = (
            ROOT / "mock_examples/mock_plastic_broom_simple.yaml"
        ).read_text()
        graph = self.engine.run(source)["contribution_graphs"][0]
        process_names = [
            node["process_name"]
            for node in graph["nodes"]
            if node["kind"] == "process"
        ]
        self.assertEqual(
            process_names.count("Mock grid electricity, medium voltage"),
            1,
        )
        self.assertEqual(
            process_names.count(
                "Mock freight transport, small truck, direct emissions only"
            ),
            1,
        )

    def test_plastic_broom_returns_recursive_climate_contribution_graph(self):
        source = (ROOT / "mock_examples/mock_plastic_broom.yaml").read_text()
        original_lca = core_engine.bc.LCA
        with mock.patch.object(core_engine.bc, "LCA", wraps=original_lca) as lca:
            result = self.engine.run(source)
        self.assertEqual(lca.call_count, 1)

        self.assertEqual(result["result_schema_version"], 3)
        self.assertEqual(len(result["contribution_graphs"]), 1)
        graph = result["contribution_graphs"][0]
        self.assertEqual(
            graph["label"],
            "climate change | global warming potential (GWP100)",
        )
        self.assertAlmostEqual(graph["total_score"], 0.9488709719424245)
        self.assertEqual(graph["status"], "complete")
        self.assertAlmostEqual(graph["coverage"], 1)
        self.assertEqual(graph["unexpanded_score"], 0)

        process_nodes = [
            node for node in graph["nodes"] if node["kind"] == "process"
        ]
        names = [node["process_name"] for node in process_nodes]
        self.assertEqual(names.count("Mock plastic broom assembly"), 1)
        self.assertEqual(
            names.count("Mock polypropylene granulate, at plant"), 1
        )
        self.assertEqual(
            names.count("Mock freight transport, small truck"), 1
        )
        self.assertEqual(
            names.count("Mock grid electricity, medium voltage"), 2
        )
        self.assertEqual(
            [node["depth"] for node in graph["nodes"]],
            [0, 1, 2, 2, 3, 3],
        )

        by_id = {node["id"]: node for node in graph["nodes"]}
        self.assertTrue(
            all(
                flow["process_occurrence_id"] in by_id
                for flow in graph["flows"]
            )
        )
        children_by_consumer: dict[str, list[str]] = {}
        for edge in graph["edges"]:
            children_by_consumer.setdefault(edge["consumer_id"], []).append(
                edge["producer_id"]
            )
        for node in graph["nodes"]:
            child_score = sum(
                by_id[child]["cumulative_score"]
                for child in children_by_consumer.get(node["id"], [])
            )
            self.assertTrue(
                math.isclose(
                    node["direct_score"]
                    + child_score
                    + node["unexpanded_score"],
                    node["cumulative_score"],
                    rel_tol=core_engine.NUMERIC_REL_TOLERANCE,
                    abs_tol=core_engine.NUMERIC_ABS_TOLERANCE,
                )
            )

        grid = next(
            row
            for row in graph["activity_contributions"]
            if row["process_name"] == "Mock grid electricity, medium voltage"
        )
        self.assertEqual(grid["occurrence_count"], 2)
        self.assertAlmostEqual(grid["direct_score"], 0.41937599084246135)

        climate = next(
            category
            for category in result["process_contributions"]["categories"]
            if category["label"] == graph["label"]
        )
        self.assertEqual(climate["residual_score"], 0)
        self.assertEqual(len(climate["processes"]), 4)

        repeated = self.engine.run(source)
        self.assertEqual(
            repeated["contribution_graphs"], result["contribution_graphs"]
        )

    def test_contribution_graph_cutoff_is_reported_as_unexpanded_impact(self):
        source = (ROOT / "mock_examples/mock_plastic_broom.yaml").read_text()
        source = source.replace("cutoff: 0.001", "cutoff: 0.01")
        graph = self.engine.run(source)["contribution_graphs"][0]

        grid_nodes = [
            node
            for node in graph["nodes"]
            if node["process_name"] == "Mock grid electricity, medium voltage"
        ]
        self.assertEqual(len(grid_nodes), 1)
        freight = next(
            node
            for node in graph["nodes"]
            if node["process_name"] == "Mock freight transport, small truck"
        )
        self.assertAlmostEqual(
            freight["unexpanded_score"], 0.0033759999023675914
        )
        self.assertAlmostEqual(
            graph["unexpanded_score"], 0.0033759999023675914
        )
        self.assertEqual(graph["status"], "partial")

    def test_contribution_graph_configuration_is_validated(self):
        source = (ROOT / "mock_examples/mock_plastic_broom.yaml").read_text()
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            self.engine.run(source.replace("cutoff: 0.001", "cutoff: 1"))
        with self.assertRaisesRegex(ValueError, "was not found"):
            self.engine.run(
                source.replace("- climate change", "- missing category")
            )

    def test_mock_examples_are_not_public_case_studies(self):
        import lca_server

        public_names = lca_server.list_case_studies()
        self.assertNotIn("mock_plastic_broom", public_names)
        self.assertNotIn("mock_plastic_broom_simple", public_names)
        self.assertNotIn("mock_storage_bin", public_names)


if __name__ == "__main__":
    unittest.main()
