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

    def test_mcp_session_id_preflight_is_allowed(self):
        # A browser MCP client must send Mcp-Session-Id on every request after
        # `initialize`; without it in allow_headers the preflight is refused.
        headers = {
            **PREFLIGHT_HEADERS,
            "Access-Control-Request-Headers": "content-type,mcp-session-id",
        }

        with TestClient(self.app) as client:
            response = client.options("/mcp", headers=headers)

        self.assertEqual(response.status_code, 200)
        allowed = response.headers.get("access-control-allow-headers", "").lower()
        self.assertIn("mcp-session-id", allowed)

    def test_mcp_session_id_is_exposed_to_javascript(self):
        # The id `initialize` returns is unreadable from JS unless the response
        # names it in Access-Control-Expose-Headers. That header rides on the
        # actual response rather than the preflight, so this issues a real POST.
        with TestClient(self.app) as client:
            response = client.post(
                "/mcp",
                headers={
                    "Origin": APPROVED_ORIGIN,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "cors-test", "version": "0"},
                    },
                },
            )

        exposed = response.headers.get("access-control-expose-headers", "").lower()
        self.assertIn("mcp-session-id", exposed)

    def test_unapproved_origin_does_not_receive_allow_origin_header(self):
        headers = {**PREFLIGHT_HEADERS, "Origin": UNAPPROVED_ORIGIN}

        with TestClient(self.app) as client:
            response = client.options("/api/lca/run", headers=headers)

        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
