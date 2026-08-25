"""Tier 2: background provider intensities published on the Call 1 response.

The gate is the reconciliation invariant: for every calculated category the
score left over after removing exclusive foreground direct contributions must
equal the sum over background links of

    scaling_vector[consumer] * amount * intensity[provider]

which is exactly the arithmetic the product editor performs locally.

Tolerance note. Brightway stores technosphere exchange amounts as float32:
``0.52`` is held as ``0.5199999809265137``. The server therefore scores with
float32-rounded amounts while this invariant, like the editor, multiplies the
exact float64 amount from the spec. The residual is bounded by float32 epsilon,
``1.19e-7``, so these comparisons use a relative tolerance of ``1e-6`` rather
than the ``1e-8`` adjoint tolerance used where both sides share the same stored
amounts. Measured residuals across the bundled graphs run from ``1e-8`` to
``6e-8``. This is a storage-precision floor, not cache error: the cached
intensities are bit-identical to a full request-matrix adjoint solve.
"""

import unittest

from lca_core import LCAEngine
from lca_core import background_intensity
from lca_core import engine as core_engine
from tests.background_intensity_helpers import (
    ALL_SPEC_PATHS,
    BACKGROUND_LINKED_PATHS,
    load_spec,
)


# Bounded by float32 storage of technosphere amounts (eps 1.19e-7), an order of
# magnitude above the largest residual measured on the bundled graphs.
AMOUNT_PRECISION_REL_TOLERANCE = 1e-6
AMOUNT_PRECISION_ABS_TOLERANCE = 1e-12

FOREGROUND_ONLY_PATHS = tuple(
    path for path in ALL_SPEC_PATHS if path not in BACKGROUND_LINKED_PATHS
)


def background_link_total(result: dict, label: str) -> float:
    scaling = result["scaling_vector"]
    return sum(
        scaling[row["process_name"]] * row["amount"] * row["intensities"][label]
        for row in result["background_link_intensities"]
    )


def foreground_direct_total(result: dict, label: str) -> float:
    category = next(
        item
        for item in result["process_contributions"]["categories"]
        if item["label"] == label
    )
    return sum(
        row["direct_score"]
        for row in category["processes"]
        if row["scope"] == "foreground"
    )


class Tier2ProviderIntensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        background_intensity.clear_cache()
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()

    def assertReconciles(self, expected: float, actual: float, message: str):
        tolerance = (
            max(abs(expected), abs(actual), 1.0) * AMOUNT_PRECISION_REL_TOLERANCE
            + AMOUNT_PRECISION_ABS_TOLERANCE
        )
        self.assertLessEqual(
            abs(expected - actual),
            tolerance,
            f"{message}: {expected} != {actual}",
        )

    def test_payload_addresses_the_source_exchanges(self):
        for relative_path in BACKGROUND_LINKED_PATHS:
            with self.subTest(relative_path):
                source, spec = load_spec(relative_path)
                result = self.engine.run_base(source)
                rows = result["background_link_intensities"]
                self.assertTrue(rows, "expected background links")
                for row in rows:
                    process = spec["processes"][row["process_index"]]
                    exchange = process["inputs"][row["input_index"]]
                    self.assertEqual(row["process_name"], process["name"])
                    self.assertEqual(row["flow"], exchange["flow"])
                    self.assertEqual(row["amount"], float(exchange["amount"]))
                    self.assertTrue(exchange.get("database"))
                self.assertEqual(
                    len({row["link_id"] for row in rows}),
                    len(rows),
                    "link_id must be unique within a result",
                )

    def test_every_category_reconciles(self):
        for relative_path in BACKGROUND_LINKED_PATHS:
            with self.subTest(relative_path):
                source, _ = load_spec(relative_path)
                result = self.engine.run_base(source)
                self.assertIn("background_link_intensities", result)
                for label, impact in result["lcia"].items():
                    residual = impact["score"] - foreground_direct_total(
                        result, label
                    )
                    self.assertReconciles(
                        residual,
                        background_link_total(result, label),
                        f"{relative_path} / {label}",
                    )

    def test_perturbation_prediction_matches_exact_calculation(self):
        for relative_path in BACKGROUND_LINKED_PATHS:
            with self.subTest(relative_path):
                source, spec = load_spec(relative_path)
                baseline = self.engine.run_base(source)
                row = baseline["background_link_intensities"][0]
                scale = baseline["scaling_vector"][row["process_name"]]
                new_amount = row["amount"] * 0.5 if row["amount"] else 1.0

                edited = core_engine._load_spec(source)
                edited["processes"][row["process_index"]]["inputs"][
                    row["input_index"]
                ]["amount"] = new_amount
                import yaml as _yaml

                exact = self.engine.run_base(_yaml.safe_dump(edited))

                for label, impact in baseline["lcia"].items():
                    predicted = impact["score"] + scale * (
                        new_amount - row["amount"]
                    ) * row["intensities"][label]
                    self.assertReconciles(
                        predicted,
                        exact["lcia"][label]["score"],
                        f"{relative_path} / {label} / perturbed",
                    )

    def test_foreground_only_graphs_return_an_empty_list(self):
        for relative_path in FOREGROUND_ONLY_PATHS:
            with self.subTest(relative_path):
                source, _ = load_spec(relative_path)
                result = self.engine.run_base(source)
                self.assertEqual(result["background_link_intensities"], [])

    def test_field_is_absent_when_a_failure_disabled_the_cache(self):
        source, _ = load_spec(BACKGROUND_LINKED_PATHS[0])
        background_intensity.disable("forced for the test")
        try:
            result = self.engine.run_base(source)
        finally:
            background_intensity.clear_cache()
        self.assertNotIn("background_link_intensities", result)


if __name__ == "__main__":
    unittest.main()
