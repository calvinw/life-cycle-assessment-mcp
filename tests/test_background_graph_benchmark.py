import pathlib
import unittest

from lca_core.benchmark import (
    BenchmarkSettings,
    _occurrence_path_keys,
    serialization_sizes,
    synthetic_serialization_fixture,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]


class BackgroundGraphBenchmarkTests(unittest.TestCase):
    def test_default_settings_match_phase_zero_benchmark_contract(self):
        settings = BenchmarkSettings()
        self.assertEqual(settings.cutoff, 0.001)
        self.assertEqual(settings.biosphere_cutoff, 0.0001)
        self.assertEqual(settings.max_depth, 12)
        self.assertEqual(settings.max_calculations, 1000)
        self.assertTrue(settings.include_flows)

    def test_synthetic_fixture_has_requested_scale_and_stable_sizes(self):
        first = synthetic_serialization_fixture()
        second = synthetic_serialization_fixture()
        graph = first["contribution_graphs"][0]
        self.assertEqual(len(graph["nodes"]), 1000)
        self.assertEqual(len(graph["edges"]), 999)
        self.assertEqual(len(graph["flows"]), 1500)
        self.assertEqual(serialization_sizes(first), serialization_sizes(second))
        sizes = serialization_sizes(first)
        self.assertLess(sizes["gzip_bytes"], sizes["raw_bytes"])

    def test_union_paths_ignore_category_ids_but_preserve_occurrences(self):
        def graph(label):
            root = f"root:{label}"
            first = f"first:{label}"
            second = f"second:{label}"
            return {
                "label": label,
                "nodes": [
                    {"id": root, "kind": "functional_unit"},
                    {
                        "id": first,
                        "kind": "process",
                        "activity_id": "activity:a",
                        "database": "database",
                        "code": "a",
                    },
                    {
                        "id": second,
                        "kind": "process",
                        "activity_id": "activity:a",
                        "database": "database",
                        "code": "a",
                    },
                ],
                "edges": [
                    {
                        "producer_id": first,
                        "consumer_id": root,
                        "flow_name": "product",
                        "amount": 1.0,
                        "unit": "kg",
                    },
                    {
                        "producer_id": second,
                        "consumer_id": first,
                        "flow_name": "product",
                        "amount": 0.5,
                        "unit": "kg",
                    },
                ],
            }

        climate = _occurrence_path_keys(graph("climate"))
        toxicity = _occurrence_path_keys(graph("toxicity"))
        self.assertEqual(climate, toxicity)
        self.assertEqual(len(climate), 3)


if __name__ == "__main__":
    unittest.main()
