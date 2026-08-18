import math
import os
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
        self.original_mode = os.environ.get(
            background_intensity.CACHE_ENV_VAR
        )
        background_intensity.clear_cache()

    def tearDown(self):
        background_intensity.clear_cache()
        if self.original_mode is None:
            os.environ.pop(background_intensity.CACHE_ENV_VAR, None)
        else:
            os.environ[
                background_intensity.CACHE_ENV_VAR
            ] = self.original_mode

    def _set_mode(self, mode: str) -> None:
        os.environ[background_intensity.CACHE_ENV_VAR] = mode

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

    def test_default_mode_is_off(self):
        os.environ.pop(background_intensity.CACHE_ENV_VAR, None)
        self.assertEqual(background_intensity.configured_mode(), "off")
        self.assertEqual(background_intensity.effective_mode(), "off")

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

    def test_compare_mode_uses_reference_result_without_warning(self):
        source = (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        self._set_mode("off")
        base = self.engine.run_base(source)
        categories = list(base["lcia"])
        reference = self.engine.contribution_graphs(source, categories)

        background_intensity.clear_cache()
        self._set_mode("compare")
        with self.assertNoLogs("lca_core.engine", level="WARNING"):
            compared = self.engine.contribution_graphs(source, categories)
        self.assertEqual(compared, reference)

    def test_on_mode_uses_cached_adjoint_without_request_factorization(self):
        source = (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        self._set_mode("off")
        base = self.engine.run_base(source)
        categories = list(base["lcia"])
        reference = self.engine.contribution_graphs(source, categories)

        background_intensity.clear_cache()
        self._set_mode("on")
        with mock.patch.object(
            core_engine,
            "factorize_adjoint",
            side_effect=AssertionError("request adjoint factorization was called"),
        ):
            cached = self.engine.contribution_graphs(source, categories)
        self.assert_results_close(cached, reference)

    def test_on_mode_falls_back_once_then_stays_off_for_remaining_categories(self):
        source = (ROOT / "mock_examples/mock_storage_bin.yaml").read_text()
        self._set_mode("on")
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
        self.assertEqual(background_intensity.effective_mode(), "off")
        self.assertIn("forced cache failure", engine_logs.output[0])
        self.assertIn("forced cache failure", cache_logs.output[0])


if __name__ == "__main__":
    unittest.main()
