import importlib
import sys
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient


APPROVED_ORIGIN = "https://calvinw.github.io"
UNAPPROVED_ORIGIN = "https://example.com"
PREFLIGHT_HEADERS = {
    "Origin": APPROVED_ORIGIN,
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


class CorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Importing the HTTP adapter normally validates/downloads Brightway data.
        # CORS tests need only the transport layer, so keep them self-contained.
        with patch("lca_core.LCAEngine.ensure_ready"):
            sys.modules.pop("sse_server", None)
            sys.modules.pop("lca_server", None)
            server = importlib.import_module("sse_server")

        cls.app = server.mcp.http_app(
            transport="streamable-http",
            middleware=server.CORS_MIDDLEWARE,
        )

    def test_github_pages_preflight_is_allowed(self):
        with TestClient(self.app) as client:
            response = client.options("/api/lca/run", headers=PREFLIGHT_HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            APPROVED_ORIGIN,
        )
        self.assertIn(
            "POST",
            response.headers.get("access-control-allow-methods", ""),
        )
        self.assertIn(
            "content-type",
            response.headers.get("access-control-allow-headers", "").lower(),
        )

    def test_unapproved_origin_does_not_receive_allow_origin_header(self):
        headers = {**PREFLIGHT_HEADERS, "Origin": UNAPPROVED_ORIGIN}

        with TestClient(self.app) as client:
            response = client.options("/api/lca/run", headers=headers)

        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
