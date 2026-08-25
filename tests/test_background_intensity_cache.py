import math
import pathlib
import sqlite3
import tempfile
import types
import unittest
from unittest import mock

from lca_core import LCAEngine
from lca_core import background_intensity
from lca_core import engine as core_engine

from tests.background_intensity_helpers import configured_methods, load_spec


ROOT = pathlib.Path(__file__).resolve().parents[1]


class BackgroundIntensityCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()

    def setUp(self):
        background_intensity.clear_cache()

    def tearDown(self):
        background_intensity.clear_cache()

    def assert_results_close(self, first, second, path="result"):
        self.assertIs(type(first), type(second), path)
        if isinstance(first, dict):
            self.assertEqual(first.keys(), second.keys(), path)
            for key in first:
                self.assert_results_close(
                    first[key], second[key], f"{path}.{key}"
                )
        elif isinstance(first, list):
            self.assertEqual(len(first), len(second), path)
            for index, (left, right) in enumerate(zip(first, second, strict=True)):
                self.assert_results_close(
                    left, right, f"{path}[{index}]"
                )
        elif isinstance(first, float):
            self.assertTrue(
                math.isclose(first, second, rel_tol=1e-8, abs_tol=1e-12),
                (path, first, second),
            )
        else:
            self.assertEqual(first, second, path)

    def test_cache_is_enabled_until_a_failure_disables_it(self):
        self.assertTrue(background_intensity.enabled())
        background_intensity.disable("forced for the test")
        self.assertFalse(background_intensity.enabled())
        background_intensity.clear_cache()
        self.assertTrue(background_intensity.enabled())

    def test_database_identity_changes_with_available_metadata(self):
        databases = {
            "bafu": {
                "number": 11947,
                "modified": "2026-08-17T00:00:00",
                "processed": "first",
                "backend": "sqlite",
                "depends": ["biosphere3"],
            },
            "biosphere3": {
                "number": 4709,
                "processed": "biosphere",
                "backend": "sqlite",
            },
        }
        bd = types.SimpleNamespace(
            projects=types.SimpleNamespace(current="test-project"),
            databases=databases,
        )
        first = background_intensity.database_identity(bd, ("bafu",))
        databases["bafu"]["processed"] = "second"
        second = background_intensity.database_identity(bd, ("bafu",))
        self.assertNotEqual(first, second)
        self.assertIn("bafu", repr(second))
        self.assertIn("biosphere3", repr(second))

    def test_one_factorization_is_shared_by_multiple_categories(self):
        _, spec = load_spec("mock_examples/mock_storage_bin.yaml")
        methods = configured_methods(spec)
        self.assertGreaterEqual(len(methods), 2)
        original_splu = background_intensity.splu
        with mock.patch.object(
            background_intensity,
            "splu",
            wraps=original_splu,
        ) as factorize:
            first = background_intensity.get_background_y(
                core_engine.bd,
                core_engine.bc,
                ("mock_background",),
                methods[0],
            )
            second = background_intensity.get_background_y(
                core_engine.bd,
                core_engine.bc,
                ("mock_background",),
                methods[1],
            )
        self.assertEqual(factorize.call_count, 1)
        self.assertEqual(set(first), set(second))
        self.assertEqual(len(first), 4)

    def test_indexed_startup_guard_rejects_foreground_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "projection.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE exchanges (
                        output_database TEXT,
                        output_code TEXT,
                        input_database TEXT,
                        input_code TEXT
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO exchanges VALUES (?, ?, ?, ?)",
                    (
                        "bafu",
                        "background-process",
                        "foreground_request_test",
                        "foreground-process",
                    ),
                )
            status = {"fresh": True, "path": str(path)}
            with mock.patch(
                "lca_core.search.get_projection_status",
                return_value=status,
            ):
                with self.assertRaisesRegex(
                    background_intensity.BackgroundInvariantError,
                    "INVARIANT B1 violated",
                ):
                    background_intensity._validate_background_exchanges(
                        core_engine.bd,
                        ("bafu",),
                    )

    def _reference_graphs(self, source, categories):
        """Contribution graphs solved the direct way, with the cache disabled."""
        background_intensity.disable("reference solve for the test")
        try:
            return self.engine.contribution_graphs(source, categories)
        finally:
            background_intensity.clear_cache()

    def test_cached_result_matches_the_direct_solve_without_warning(self):
        source = (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        base = self.engine.run_base(source)
        categories = list(base["lcia"])
        reference = self._reference_graphs(source, categories)

        with self.assertNoLogs("lca_core.engine", level="WARNING"):
            cached = self.engine.contribution_graphs(source, categories)
        self.assert_results_close(cached, reference)

    def test_cache_avoids_the_per_request_adjoint_factorization(self):
        source = (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        base = self.engine.run_base(source)
        categories = list(base["lcia"])
        reference = self._reference_graphs(source, categories)

        with mock.patch.object(
            core_engine,
            "factorize_adjoint",
            side_effect=AssertionError("request adjoint factorization was called"),
        ):
            cached = self.engine.contribution_graphs(source, categories)
        self.assert_results_close(cached, reference)

    def test_cache_falls_back_once_then_stays_off_for_remaining_categories(self):
        source = (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        base = self.engine.run_base(source)
        categories = list(base["lcia"])

        with (
            mock.patch.object(
                background_intensity,
                "assemble_request_cumulative_intensities",
                side_effect=RuntimeError("forced cache failure"),
            ) as assemble,
            self.assertLogs("lca_core.engine", level="WARNING") as engine_logs,
            self.assertLogs(
                "lca_core.background_intensity", level="ERROR"
            ) as cache_logs,
        ):
            result = self.engine.contribution_graphs(source, categories)

        self.assertEqual(len(result["contribution_graphs"]), len(categories))
        self.assertEqual(assemble.call_count, 1)
        self.assertFalse(background_intensity.enabled())
        self.assertIn("forced cache failure", engine_logs.output[0])
        self.assertIn("forced cache failure", cache_logs.output[0])


if __name__ == "__main__":
    unittest.main()
