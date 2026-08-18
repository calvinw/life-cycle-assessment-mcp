import math
import unittest

import numpy as np

from lca_core import LCAEngine
from lca_core.contribution_graph import (
    ADJOINT_SCORE_ABS_TOLERANCE,
    ADJOINT_SCORE_REL_TOLERANCE,
)

from tests.background_intensity_helpers import (
    ALL_SPEC_PATHS,
    background_database_names,
    configured_methods,
    direct_intensities,
    foreground_lca,
    load_spec,
    matrix_partition,
    precomputed_background_y,
)


class BackgroundScoreDecompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()

    def test_precomputed_background_y_reproduces_every_score(self):
        for relative_path in ALL_SPEC_PATHS:
            source, spec = load_spec(relative_path)
            methods = configured_methods(spec)
            database_names = background_database_names(spec)
            cached_by_method = {
                method: precomputed_background_y(database_names, method)
                for method in methods
            }

            with foreground_lca(source, methods[0]) as (_, activities, lca):
                partition = matrix_partition(lca, activities)
                foreground_rows = partition["foreground_product_rows"]
                background_rows = partition["background_product_rows"]
                foreground_columns = partition["foreground_activity_columns"]

                a_ff = lca.technosphere_matrix[foreground_rows, :][
                    :, foreground_columns
                ].toarray()
                f_f = np.asarray(lca.demand_array).ravel()[foreground_rows]
                s_f = np.linalg.solve(a_ff, f_f)
                a_bf = lca.technosphere_matrix[background_rows, :][
                    :, foreground_columns
                ]
                d_b_demand = np.asarray(-a_bf @ s_f).ravel()

                for method in methods:
                    with self.subTest(
                        spec=relative_path,
                        category=" | ".join(method[1:]),
                    ):
                        if method != methods[0]:
                            lca.switch_method(method)
                        lca.lcia()
                        direct = direct_intensities(lca)
                        d_f = direct[foreground_columns]
                        cached = cached_by_method[method]
                        y_b = np.array(
                            [
                                cached[node_id]
                                for node_id in partition["background_product_ids"]
                            ],
                            dtype=float,
                        )
                        decomposed = float(d_f @ s_f + d_b_demand @ y_b)
                        reference = float(lca.score)
                        self.assertTrue(
                            math.isclose(
                                decomposed,
                                reference,
                                rel_tol=ADJOINT_SCORE_REL_TOLERANCE,
                                abs_tol=ADJOINT_SCORE_ABS_TOLERANCE,
                            ),
                            (relative_path, method, decomposed, reference),
                        )


if __name__ == "__main__":
    unittest.main()
