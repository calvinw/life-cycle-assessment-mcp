import json
import pathlib
import unittest

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

    def test_installer_is_idempotent_and_database_has_three_processes(self):
        status = ensure_mock_background_database(bd)
        self.assertFalse(status["changed"])
        self.assertEqual(status["activities"], 3)
        self.assertEqual(len(bd.Database(DATABASE_NAME)), 3)

    def test_mock_database_is_searchable_through_public_api(self):
        results = self.engine.search_activities(
            "polypropylene", database=DATABASE_NAME
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["key"], [DATABASE_NAME, "mock-polypropylene"])

    def test_one_and_two_background_process_examples_calculate(self):
        storage = self.engine.run(
            (ROOT / "case_studies/mock_storage_bin.yaml").read_text()
        )
        broom = self.engine.run(
            (ROOT / "case_studies/mock_plastic_broom.yaml").read_text()
        )

        storage_background = [
            node for node in storage["sankey"]["nodes"]
            if node.get("scope") == "background"
        ]
        broom_background = [
            node for node in broom["sankey"]["nodes"]
            if node.get("scope") == "background"
        ]
        self.assertEqual(len(storage_background), 1)
        self.assertEqual(len(broom_background), 2)
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
        self.assertAlmostEqual(storage_climate, 1.44, places=6)
        self.assertAlmostEqual(broom_climate, 0.948871, places=6)
        self.assertFalse(
            any(
                name.startswith(core_engine.FOREGROUND_DB_PREFIX)
                for name in bd.databases
            )
        )

    def test_bundled_mock_case_studies_match_their_yaml(self):
        for name in ("mock_plastic_broom", "mock_storage_bin"):
            yaml_text = (ROOT / "case_studies" / f"{name}.yaml").read_text()
            bundle = json.loads(
                (ROOT / "case_studies" / f"{name}.json").read_text()
            )
            self.assertEqual(bundle["product_graph"], yaml_text)
            self.assertTrue(bundle["svg_structure"].startswith("<svg"))
            self.assertTrue(bundle["svg_scaled"].startswith("<svg"))
            self.assertTrue(bundle["unit_process_svgs"])


if __name__ == "__main__":
    unittest.main()
