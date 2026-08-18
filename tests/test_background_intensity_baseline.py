import argparse
import json
import math
import pathlib
import sys
import unittest

import yaml

from lca_core import LCAEngine


ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "golden_scores.json"
SPEC_PATHS = (
    "case_studies/cotton_fiber.yaml",
    "case_studies/jacket.yaml",
    "case_studies/polyester_tshirt.yaml",
    "case_studies/wool_yarn.yaml",
    "mock_examples/mock_plastic_broom.yaml",
    "mock_examples/mock_plastic_broom_simple.yaml",
    "mock_examples/mock_storage_bin.yaml",
    "bafu_examples/cotton_fiber_bafu.yaml",
    "bafu_examples/plastic_broom.yaml",
    "bafu_examples/polyester_tshirt_bafu.yaml",
    "bafu_examples/wool_yarn_bafu.yaml",
)
SCORE_RTOL = 1e-12
UPDATE_GOLDENS = False


def _calculate_scores(engine: LCAEngine) -> dict:
    specs = {}
    for relative_path in SPEC_PATHS:
        source_path = ROOT / relative_path
        source = source_path.read_text()
        configured = yaml.safe_load(source)["lcia"]["categories"]
        result = engine.run(source)
        actual_labels = list(result["lcia"])

        assert len(actual_labels) == len(configured), relative_path
        for category in configured:
            matches = [
                label
                for label in actual_labels
                if str(category).casefold() in label.casefold()
            ]
            assert len(matches) == 1, (relative_path, category, actual_labels)

        specs[relative_path] = {
            "method": result["method"],
            "categories": result["lcia"],
        }
    return {"schema_version": 1, "specs": specs}


class BackgroundIntensityBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()

    def test_golden_scores(self):
        actual = _calculate_scores(self.engine)

        if UPDATE_GOLDENS:
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(
                json.dumps(actual, indent=2, sort_keys=True) + "\n"
            )

        self.assertTrue(
            GOLDEN_PATH.exists(),
            f"Missing {GOLDEN_PATH.relative_to(ROOT)}; regenerate explicitly with "
            "python -m tests.test_background_intensity_baseline --update-goldens",
        )
        expected = json.loads(GOLDEN_PATH.read_text())

        self.assertEqual(actual["schema_version"], expected["schema_version"])
        self.assertEqual(set(actual["specs"]), set(expected["specs"]))
        for relative_path, actual_spec in actual["specs"].items():
            expected_spec = expected["specs"][relative_path]
            self.assertEqual(actual_spec["method"], expected_spec["method"])
            self.assertEqual(
                set(actual_spec["categories"]),
                set(expected_spec["categories"]),
            )
            for category, actual_result in actual_spec["categories"].items():
                expected_result = expected_spec["categories"][category]
                self.assertEqual(actual_result["unit"], expected_result["unit"])
                self.assertTrue(
                    math.isclose(
                        actual_result["score"],
                        expected_result["score"],
                        rel_tol=SCORE_RTOL,
                        abs_tol=0.0,
                    ),
                    (
                        relative_path,
                        category,
                        actual_result["score"],
                        expected_result["score"],
                    ),
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--update-goldens", action="store_true")
    arguments, unittest_arguments = parser.parse_known_args()
    UPDATE_GOLDENS = arguments.update_goldens
    unittest.main(argv=[sys.argv[0], *unittest_arguments])
