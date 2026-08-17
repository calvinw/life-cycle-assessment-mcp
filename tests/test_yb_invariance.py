import unittest

import numpy as np

from lca_core import LCAEngine

from tests.background_intensity_helpers import (
    background_y_from_full_lca,
    direct_intensities,
    foreground_lca,
    load_spec,
    resolve_method,
)


TWO_PROCESS_BAFU_GRAPH = """
name: Two-stage BAFU broom
functional_unit:
  description: 1 plastic broom
  amount: 1.0
  unit: unit
products:
  - { name: Prepared broom materials, unit: unit }
  - { name: Plastic broom, unit: unit }
processes:
  - name: Prepare broom materials
    reference_output: { flow: Prepared broom materials, amount: 1.0, unit: unit }
    inputs:
      - { flow: "Polylactide, granulate, at plant", location: GLO, database: bafu, amount: 0.52, unit: kg }
      - { flow: "Nylon 6, at plant", location: RER, database: bafu, amount: 0.03, unit: kg }
      - { flow: "Transport, freight, lorry, 16t-32t gross weight, fleet average", location: RER, database: bafu, amount: 0.1055, unit: tkm }
  - name: Assemble broom
    reference_output: { flow: Plastic broom, amount: 1.0, unit: unit }
    inputs:
      - { flow: Prepared broom materials, amount: 1.0, unit: unit }
reference_process: Assemble broom
lcia:
  method_name: EF v3.1
  categories:
    - climate change
"""


class BackgroundIntensityInvarianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LCAEngine()
        cls.engine.ensure_ready()
        cls.method = resolve_method("EF v3.1", "climate change")

    def _background_y(self, source: str) -> dict[int, float]:
        with foreground_lca(source, self.method) as (_, activities, lca):
            lca.lcia()
            return background_y_from_full_lca(lca, activities)

    def _background_system(self, source: str):
        with foreground_lca(source, self.method) as (_, activities, lca):
            lca.lcia()
            foreground_ids = {activity.id for activity in activities.values()}
            product_indices = {
                node_id: index
                for node_id, index in lca.dicts.product.items()
                if node_id not in foreground_ids
            }
            activity_indices = {
                node_id: index
                for node_id, index in lca.dicts.activity.items()
                if node_id not in foreground_ids
            }
            product_ids = sorted(product_indices)
            activity_ids = sorted(activity_indices)
            rows = np.array([product_indices[node_id] for node_id in product_ids])
            columns = np.array(
                [activity_indices[node_id] for node_id in activity_ids]
            )
            a_bb = lca.technosphere_matrix[rows, :][:, columns].tocsr()
            d_b = direct_intensities(lca)[columns]
            return product_ids, activity_ids, a_bb, d_b

    def assert_background_y_equal(self, first: dict, second: dict):
        self.assertEqual(set(first), set(second))
        node_ids = sorted(first)
        np.testing.assert_allclose(
            [first[node_id] for node_id in node_ids],
            [second[node_id] for node_id in node_ids],
            rtol=1e-12,
            atol=0.0,
        )

    def test_different_bafu_provider_sets_have_identical_background_system(self):
        broom_source, _ = load_spec("bafu_examples/plastic_broom.yaml")
        shirt_source, _ = load_spec("bafu_examples/polyester_tshirt_bafu.yaml")
        broom_products, broom_activities, broom_a, broom_d = (
            self._background_system(broom_source)
        )
        shirt_products, shirt_activities, shirt_a, shirt_d = (
            self._background_system(shirt_source)
        )

        self.assertEqual(broom_products, shirt_products)
        self.assertEqual(broom_activities, shirt_activities)
        delta = broom_a - shirt_a
        delta.eliminate_zeros()
        self.assertEqual(delta.nnz, 0)
        np.testing.assert_array_equal(broom_d, shirt_d)

    def test_different_foreground_process_counts_have_identical_background_y(self):
        broom_source, _ = load_spec("bafu_examples/plastic_broom.yaml")
        self.assert_background_y_equal(
            self._background_y(broom_source),
            self._background_y(TWO_PROCESS_BAFU_GRAPH),
        )


if __name__ == "__main__":
    unittest.main()
