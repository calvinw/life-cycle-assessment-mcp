import inspect
import json
import pathlib
import time
import unittest

from lca_core import engine as core_engine


ROOT = pathlib.Path(__file__).resolve().parents[1]
SENSITIVE_MARKER = "sensitive-product-marker-do-not-log"


class PerformanceInstrumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "case_studies/polyester_tshirt.yaml").read_text()
        cls.source = source.replace(
            "Polyester T-shirt — 1 unit",
            f"Polyester T-shirt — 1 unit {SENSITIVE_MARKER}",
        )

    @staticmethod
    def _record(output):
        return json.loads(output.records[0].getMessage())

    def test_base_instrumentation_preserves_result_and_records_expected_phases(self):
        expected = core_engine._run_analysis(
            self.source,
            include_contribution_graphs=False,
        )
        with self.assertLogs("lca.performance", level="INFO") as output:
            actual = core_engine.run_base_analysis(self.source)

        self.assertEqual(actual, expected)
        self.assertEqual(len(output.records), 1)
        record = self._record(output)
        self.assertEqual(record["event"], "lca_engine_performance")
        self.assertEqual(record["operation"], "base")
        self.assertGreaterEqual(record["total_seconds"], 0)
        self.assertTrue(
            {
                "yaml_parsing_and_validation",
                "brightway_project_readiness",
                "temporary_foreground_creation",
                "lca_construction",
                "lci_factorization",
                "inventory_base_result_construction",
                "lcia_calculation_and_direct_contributions",
                "result_validation",
            }.issubset(record["phases"])
        )
        self.assertNotIn(SENSITIVE_MARKER, output.output[0])
        self.assertNotIn("product_graph", output.output[0])

    def test_contribution_records_adjoint_and_per_category_timings(self):
        base = core_engine._run_analysis(
            self.source,
            include_contribution_graphs=False,
        )
        categories = list(base["lcia"])
        expected = core_engine._run_contribution_analysis(
            self.source,
            categories,
            result_id=base["result_id"],
        )
        with self.assertLogs("lca.performance", level="INFO") as output:
            result = core_engine.run_contribution_analysis(
                self.source,
                categories,
                result_id=base["result_id"],
            )

        self.assertEqual(result, expected)
        self.assertEqual(len(output.records), 1)
        record = self._record(output)
        self.assertEqual(record["operation"], "contribution")
        phases = record["phases"]
        self.assertIn("adjoint_transpose_factorization", phases)
        self.assertEqual(
            [
                item["category"]
                for item in phases["contribution_traversal_per_category"][
                    "categories"
                ]
            ],
            categories,
        )
        self.assertTrue(
            all(
                item["seconds"] >= 0
                for item in phases["contribution_traversal_per_category"][
                    "categories"
                ]
            )
        )
        self.assertNotIn(SENSITIVE_MARKER, output.output[0])

    def test_rest_log_records_serialization_without_content(self):
        import lca_server

        content = {"result_id": "stable", "private": SENSITIVE_MARKER}
        with self.assertLogs("lca.performance", level="INFO") as output:
            response = lca_server._performance_json_response(
                operation="base",
                request_started=time.perf_counter(),
                content=content,
            )

        self.assertEqual(json.loads(response.body), content)
        self.assertEqual(len(output.records), 1)
        record = self._record(output)
        self.assertEqual(record["event"], "lca_rest_performance")
        self.assertEqual(record["operation"], "base")
        self.assertIn("json_response_serialization", record["phases"])
        self.assertNotIn(SENSITIVE_MARKER, output.output[0])

    def test_stateless_endpoints_do_not_retain_unused_forward_factorization(self):
        implementations = (
            inspect.getsource(core_engine._run_analysis)
            + inspect.getsource(core_engine._run_contribution_analysis)
        )
        self.assertNotIn("lci(factorize=True)", implementations)
        self.assertEqual(implementations.count("lca.lci()"), 2)


if __name__ == "__main__":
    unittest.main()
