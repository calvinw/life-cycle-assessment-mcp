import io
import unittest
import zipfile

from lca_core.interchange import (
    InterchangeError,
    export_ecospold2,
    export_interchange,
    preview_ecospold2,
    preview_interchange,
)
from tests.test_tidas_interchange import _two_process_model_bundle


class EcoSpold2InterchangeTests(unittest.TestCase):
    def test_export_is_deterministic_and_round_trips(self):
        bundle, model_id = _two_process_model_bundle()

        first = export_ecospold2(bundle, model_id)
        second = export_ecospold2(bundle, model_id)
        self.assertEqual(first, second)

        preview = preview_ecospold2(first)
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["format"], "ecospold2")
        self.assertEqual(
            preview["summary"],
            {
                "model": 1,
                "process": 2,
                "flow": 1,
                "flow_property": 1,
                "unit_group": 1,
                "source": 0,
                "contact": 0,
            },
        )
        model = next(row for row in preview["datasets"] if row["type"] == "model")
        names = {
            item["dataSetInternalID"]: item["referenceToProcess"]["shortDescription"]
            for item in model["payload"]["processInstances"]
        }
        connection = model["payload"]["connections"][0]
        self.assertEqual(names[connection["fromInstanceId"]], "Steel production")
        self.assertEqual(names[connection["toInstanceId"]], "Steel finishing")

    def test_export_contains_one_schema_document_per_process(self):
        bundle, model_id = _two_process_model_bundle()
        package = export_ecospold2(bundle, model_id)

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), 2)
            self.assertTrue(all(name.startswith("datasets/") and name.endswith(".spold") for name in names))
            self.assertTrue(all(b"http://www.EcoInvent.org/EcoSpold02" in archive.read(name) for name in names))

    def test_export_dispatch_accepts_ecospold2(self):
        bundle, model_id = _two_process_model_bundle()
        package = export_interchange("ecospold2", bundle, model_id)
        self.assertEqual(preview_interchange(package)["format"], "ecospold2")

    def test_dispatch_detects_zip_and_raw_xml(self):
        bundle, model_id = _two_process_model_bundle()
        package = export_ecospold2(bundle, model_id)
        self.assertEqual(preview_interchange(package)["format"], "ecospold2")

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            raw = archive.read(archive.namelist()[0])
        preview = preview_interchange(raw)
        self.assertEqual(preview["format"], "ecospold2")
        self.assertEqual(preview["summary"]["process"], 1)

    def test_xml_entity_declarations_are_rejected(self):
        package = b'''<?xml version="1.0"?>
        <!DOCTYPE ecoSpold [<!ENTITY unsafe "unsafe">]>
        <ecoSpold xmlns="http://www.EcoInvent.org/EcoSpold02">&unsafe;</ecoSpold>'''
        with self.assertRaises(InterchangeError) as raised:
            preview_ecospold2(package)
        self.assertEqual(raised.exception.code, "INVALID_ECOSPOLD2_XML")


if __name__ == "__main__":
    unittest.main()
