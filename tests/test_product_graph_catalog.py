import importlib
import sys
import unittest
from unittest.mock import patch

import yaml
from starlette.testclient import TestClient


EXPECTED_IDS = [
    "cotton_fiber",
    "cotton_fiber_bafu_linked",
    "jacket",
    "mock_plastic_broom",
    "mock_plastic_broom_simple",
    "plastic_broom",
    "polyester_tshirt",
    "polyester_tshirt_bafu_linked",
    "wool_yarn",
    "wool_yarn_bafu_linked",
]


class ProductGraphCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("lca_core.LCAEngine.ensure_ready"):
            sys.modules.pop("lca_server", None)
            cls.server = importlib.import_module("lca_server")

    def test_catalog_returns_every_yaml_document(self):
        catalog = self.server.list_product_graphs()

        self.assertEqual(catalog["default_id"], "jacket")
        self.assertEqual(
            [item["id"] for item in catalog["product_graphs"]],
            EXPECTED_IDS,
        )
        for item in catalog["product_graphs"]:
            self.assertEqual(item["filename"], f"{item['id']}.yaml")
            document = yaml.safe_load(item["product_graph"])
            self.assertEqual(item["name"], document["name"])

    def test_rest_endpoint_returns_the_catalog_in_one_call(self):
        app = self.server.mcp.http_app(transport="streamable-http")
        with TestClient(app) as client:
            response = client.get("/api/product-graphs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["default_id"], "jacket")
        self.assertEqual(len(response.json()["product_graphs"]), 10)


if __name__ == "__main__":
    unittest.main()
