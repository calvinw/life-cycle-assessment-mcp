import importlib
import io
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from lca_core.interchange.archive import MAX_PACKAGE_BYTES


FIXTURE = Path(__file__).parent / "fixtures" / "ilcd_plastic_broom.zip"


class InterchangeRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("lca_core.LCAEngine.ensure_ready"):
            sys.modules.pop("lca_server", None)
            cls.server = importlib.import_module("lca_server")
        cls.app = cls.server.mcp.http_app(transport="streamable-http")

    def test_ilcd_package_imports_through_existing_route(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/import/openlca",
                content=FIXTURE.read_bytes(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["format"], "ilcd-xml")
        self.assertEqual(response.json()["summary"]["model"], 1)

    def test_declared_oversized_package_is_rejected_before_conversion(self):
        with patch.object(self.server, "preview_interchange") as preview:
            with TestClient(self.app) as client:
                response = client.post(
                    "/api/interchange/import/openlca",
                    content=b"small",
                    headers={"Content-Length": str(MAX_PACKAGE_BYTES + 1)},
                )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "PACKAGE_TOO_LARGE")
        preview.assert_not_called()

    def test_stream_limit_rejects_an_inaccurate_content_length(self):
        with patch.object(self.server, "MAX_PACKAGE_BYTES", 4):
            with patch.object(self.server, "preview_interchange") as preview:
                with TestClient(self.app) as client:
                    response = client.post(
                        "/api/interchange/import/openlca",
                        content=b"12345",
                        headers={"Content-Length": "3"},
                    )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "PACKAGE_TOO_LARGE")
        preview.assert_not_called()

    def test_invalid_content_length_has_stable_error(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/import/openlca",
                content=b"small",
                headers={"Content-Length": "not-a-number"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_CONTENT_LENGTH")

    def test_unknown_zip_layout_has_stable_error(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("unknown.txt", "unknown")
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/import/openlca",
                content=output.getvalue(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_PACKAGE_FORMAT")

    def test_unexpected_errors_do_not_leak_details(self):
        with patch.object(
            self.server,
            "preview_interchange",
            side_effect=RuntimeError("private implementation detail"),
        ):
            with TestClient(self.app) as client:
                response = client.post(
                    "/api/interchange/import/openlca",
                    content=b"anything",
                )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "IMPORT_FAILED")
        self.assertNotIn("private implementation detail", response.text)


if __name__ == "__main__":
    unittest.main()
