import unittest

from lca_core import LCAEngine

from tests.background_intensity_helpers import (
    BACKGROUND_LINKED_PATHS,
    configured_methods,
    foreground_lca,
    load_spec,
    matrix_partition,
)


class BackgroundIsolationInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()

    def test_background_columns_never_reference_foreground_products(self):
        for relative_path in BACKGROUND_LINKED_PATHS:
            with self.subTest(spec=relative_path):
                source, spec = load_spec(relative_path)
                method = configured_methods(spec)[0]
                with foreground_lca(source, method) as (_, activities, lca):
                    partition = matrix_partition(lca, activities)
                    foreground_rows = partition["foreground_product_rows"]
                    background_rows = partition["background_product_rows"]
                    foreground_columns = partition["foreground_activity_columns"]
                    background_columns = partition["background_activity_columns"]

                    self.assertEqual(len(foreground_rows), len(activities))
                    self.assertGreater(len(background_rows), 0)
                    self.assertGreater(len(background_columns), 0)

                    a_fb = lca.technosphere_matrix[foreground_rows, :][
                        :, background_columns
                    ]
                    a_bf = lca.technosphere_matrix[background_rows, :][
                        :, foreground_columns
                    ]
                    self.assertEqual(a_fb.nnz, 0, relative_path)
                    self.assertGreater(a_bf.nnz, 0, relative_path)


if __name__ == "__main__":
    unittest.main()
