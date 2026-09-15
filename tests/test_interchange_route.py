import importlib
import io
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from lca_core.interchange import preview_interchange
from lca_core.interchange.archive import MAX_PACKAGE_BYTES
from tests.test_interchange_export import _multi_process_bundle


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

    def test_openlca_export_returns_downloadable_zip(self):
        bundle, model_id, _ = _multi_process_bundle()
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/export",
                json={"format": "openlca-json-ld", "model_id": model_id, "datasets": bundle},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="prism-export.openlca.zip"',
        )
        self.assertEqual(preview_interchange(response.content)["format"], "openlca-json-ld")

    def test_ilcd_export_returns_downloadable_zip(self):
        bundle, model_id, _ = _multi_process_bundle()
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/export",
                json={"format": "ilcd-xml", "model_id": model_id, "datasets": bundle},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="prism-export.ilcd.zip"',
        )
        self.assertEqual(preview_interchange(response.content)["format"], "ilcd-xml")

    def test_unknown_export_format_has_stable_error(self):
        bundle, _, _ = _multi_process_bundle()
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/export",
                json={"format": "unknown", "datasets": bundle},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_EXPORT_FORMAT")

    def test_malformed_export_json_has_stable_error(self):
        with TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/export",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "MALFORMED_EXPORT_REQUEST")

    def test_export_stream_limit_rejects_inaccurate_content_length(self):
        with (
            patch.object(self.server, "MAX_PACKAGE_BYTES", 4),
            patch.object(self.server, "export_interchange") as export,
            TestClient(self.app) as client,
        ):
            response = client.post(
                "/api/interchange/export",
                content=b"12345",
                headers={"Content-Length": "3", "Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "EXPORT_REQUEST_TOO_LARGE")
        export.assert_not_called()

    def test_unexpected_export_errors_do_not_leak_details(self):
        with patch.object(
            self.server,
            "export_interchange",
            side_effect=RuntimeError("private export detail"),
        ), TestClient(self.app) as client:
            response = client.post(
                "/api/interchange/export",
                json={"format": "ilcd-xml", "datasets": {}},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "EXPORT_FAILED")
        self.assertNotIn("private export detail", response.text)

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
