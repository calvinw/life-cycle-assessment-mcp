import unittest

from lca_core.interchange import (
    InterchangeError,
    export_interchange,
    export_simapro,
    preview_interchange,
    preview_simapro,
)
from tests.test_tidas_interchange import _two_process_model_bundle


class SimaProInterchangeTests(unittest.TestCase):
    def test_export_is_deterministic_and_round_trips(self):
        bundle, model_id = _two_process_model_bundle()
        first = export_simapro(bundle, model_id)
        self.assertEqual(first, export_simapro(bundle, model_id))
        self.assertTrue(first.lstrip(b"\xef\xbb\xbf").startswith(b"{SimaPro "))

        preview = preview_simapro(first)
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["format"], "simapro-csv")
        self.assertEqual(preview["summary"]["process"], 2)
        self.assertEqual(preview["summary"]["flow"], 1)
        model = next(row for row in preview["datasets"] if row["type"] == "model")
        names = {
            item["dataSetInternalID"]: item["referenceToProcess"]["shortDescription"]
            for item in model["payload"]["processInstances"]
        }
        connection = model["payload"]["connections"][0]
        self.assertEqual(names[connection["fromInstanceId"]], "Steel production")
        self.assertEqual(names[connection["toInstanceId"]], "Steel finishing")

    def test_dispatch_detects_and_exports_simapro(self):
        bundle, model_id = _two_process_model_bundle()
        package = export_interchange("simapro-csv", bundle, model_id)
        self.assertEqual(preview_interchange(package)["format"], "simapro-csv")

    def test_comma_separator_is_accepted(self):
        sample = b'''{SimaPro 9.6.0.0}\n{processes}\n{Project: Example}\n{CSV Format version: 9.0.0}\n{CSV separator: Comma}\n{Decimal separator: .}\n\nProcess\n\nProcess name\nExample process\n\nProducts\nExample product,kg,1,100,not defined,Example,\n\nEnd\n'''
        preview = preview_simapro(sample)
        self.assertEqual(preview["summary"]["process"], 1)
        self.assertEqual(preview["summary"]["flow"], 1)

    def test_methods_export_is_rejected(self):
        sample = b"{SimaPro 9.6.0.0}\n{methods}\n{CSV separator: Semicolon}\n"
        with self.assertRaises(InterchangeError) as raised:
            preview_simapro(sample)
        self.assertEqual(raised.exception.code, "UNSUPPORTED_SIMAPRO_EXPORT_TYPE")


if __name__ == "__main__":
    unittest.main()
