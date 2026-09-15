import io
import json
import unittest
import uuid
import zipfile

from lca_core.interchange import (
    InterchangeError,
    export_openlca,
    preview_interchange,
    preview_openlca,
)


def _id() -> str:
    return str(uuid.uuid4())


class OpenLcaInterchangeTests(unittest.TestCase):
    def setUp(self):
        self.unit_group_id = _id()
        self.flow_property_id = _id()
        self.flow_id = _id()
        self.process_id = _id()
        self.model_id = _id()
        self.bundle = {
            "unit_groups": [
                {
                    "id": self.unit_group_id,
                    "type": "unit_group",
                    "name": "Units of mass",
                    "description": "Mass units",
                    "payload": {
                        "unitGroupInformation": {
                            "dataSetInformation": {
                                "name": [{"lang": "en", "text": "Units of mass"}],
                                "classification": ["Technical", "Mass"],
                                "generalComment": [],
                            },
                            "quantitativeReference": {"referenceToReferenceUnit": 1},
                        },
                        "units": [
                            {
                                "dataSetInternalID": 1,
                                "name": "kg",
                                "meanValue": 1,
                                "generalComment": [],
                            }
                        ],
                        "administrativeInformation": {
                            "dataSetVersion": "01.01.000",
                            "timeStamp": "2026-09-15T00:00:00Z",
                        },
                    },
                }
            ],
            "flow_properties": [
                {
                    "id": self.flow_property_id,
                    "type": "flow_property",
                    "name": "Mass",
                    "description": "",
                    "payload": {
                        "flowPropertiesInformation": {
                            "dataSetInformation": {
                                "name": [{"lang": "en", "text": "Mass"}],
                                "classification": [],
                                "generalComment": [],
                            },
                            "quantitativeReference": {
                                "referenceToReferenceUnitGroup": {
                                    "type": "unit_group",
                                    "refObjectId": self.unit_group_id,
                                    "shortDescription": "Units of mass",
                                }
                            },
                        },
                        "administrativeInformation": {"dataSetVersion": "01.01.000"},
                    },
                }
            ],
            "flows": [
                {
                    "id": self.flow_id,
                    "type": "flow",
                    "name": "Steel",
                    "description": "Steel product",
                    "payload": {
                        "flowInformation": {
                            "dataSetInformation": {
                                "name": {
                                    "baseName": [{"lang": "en", "text": "Steel"}],
                                    "treatmentStandardsRoutes": [],
                                    "mixAndLocationTypes": [],
                                },
                                "classification": [],
                                "generalComment": [],
                            },
                            "quantitativeReference": {
                                "referenceToReferenceFlowProperty": 1
                            },
                        },
                        "modellingAndValidation": {"typeOfDataSet": "Product flow"},
                        "flowProperties": [
                            {
                                "dataSetInternalID": 1,
                                "referenceToFlowPropertyDataSet": {
                                    "type": "flow_property",
                                    "refObjectId": self.flow_property_id,
                                    "shortDescription": "Mass",
                                },
                                "meanValue": 1,
                                "generalComment": [],
                            }
                        ],
                        "administrativeInformation": {"dataSetVersion": "01.01.000"},
                    },
                }
            ],
            "processes": [
                {
                    "id": self.process_id,
                    "type": "process",
                    "name": "Steel production",
                    "description": "Makes steel",
                    "payload": {
                        "processInformation": {
                            "dataSetInformation": {
                                "name": {
                                    "baseName": [
                                        {"lang": "en", "text": "Steel production"}
                                    ],
                                    "treatmentStandardsRoutes": [],
                                    "mixAndLocationTypes": [],
                                },
                                "classification": [],
                                "generalComment": [],
                            },
                            "quantitativeReference": {"referenceToReferenceFlow": 1},
                            "geography": {"location": "GLO"},
                        },
                        "modellingAndValidation": {
                            "typeOfDataSet": "Unit process, single operation"
                        },
                        "administrativeInformation": {"dataSetVersion": "01.01.000"},
                        "exchanges": [
                            {
                                "dataSetInternalID": 1,
                                "referenceToFlowDataSet": {
                                    "type": "flow",
                                    "refObjectId": self.flow_id,
                                    "shortDescription": "Steel",
                                },
                                "exchangeDirection": "Output",
                                "meanAmount": 1,
                                "resultingAmount": 1,
                                "generalComment": [],
                            }
                        ],
                    },
                }
            ],
            "models": [
                {
                    "id": self.model_id,
                    "type": "model",
                    "name": "Steel system",
                    "description": "One-process product system",
                    "payload": {
                        "modelInformation": {
                            "dataSetInformation": {
                                "name": {
                                    "baseName": [
                                        {"lang": "en", "text": "Steel system"}
                                    ],
                                    "treatmentStandardsRoutes": [],
                                    "mixAndLocationTypes": [],
                                },
                                "classification": [],
                                "generalComment": [],
                            },
                            "quantitativeReference": {
                                "referenceToReferenceProcess": 1
                            },
                        },
                        "processInstances": [
                            {
                                "dataSetInternalID": 1,
                                "referenceToProcess": {
                                    "type": "process",
                                    "refObjectId": self.process_id,
                                    "shortDescription": "Steel production",
                                },
                                "multiplicationFactor": 1,
                            }
                        ],
                        "connections": [],
                        "administrativeInformation": {
                            "dataSetVersion": "01.01.000"
                        },
                    },
                }
            ],
            "sources": [],
            "contacts": [],
        }

    def test_export_is_deterministic_and_has_openlca_layout(self):
        first = export_openlca(self.bundle)
        second = export_openlca(self.bundle)
        self.assertEqual(first, second)

        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(json.loads(archive.read("olca-schema.json")), {"version": 2})
            process = json.loads(
                archive.read(f"processes/{self.process_id}.json")
            )
            system = json.loads(
                archive.read(f"product_systems/{self.model_id}.json")
            )

        self.assertEqual(process["@type"], "Process")
        self.assertEqual(process["exchanges"][0]["flow"]["@id"], self.flow_id)
        self.assertEqual(process["exchanges"][0]["unit"]["name"], "kg")
        self.assertTrue(process["exchanges"][0]["isQuantitativeReference"])
        self.assertEqual(system["refProcess"]["@id"], self.process_id)
        self.assertEqual(system["refExchange"]["internalId"], 1)

    def test_unchanged_export_round_trips_exact_payloads(self):
        preview = preview_openlca(export_openlca(self.bundle))
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["summary"]["model"], 1)
        imported = {row["id"]: row for row in preview["datasets"]}
        for plural in self.bundle.values():
            for original in plural:
                self.assertEqual(imported[original["id"]]["payload"], original["payload"])

    def test_dispatch_detects_openlca_json_ld(self):
        preview = preview_interchange(export_openlca(self.bundle))
        self.assertEqual(preview["format"], "openlca-json-ld")

    def test_dispatch_accepts_openlca_desktop_schema_five_manifest(self):
        exported = export_openlca(self.bundle)
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(exported)) as source, zipfile.ZipFile(
            output, "w"
        ) as target:
            target.writestr("openlca.json", '{"schemaVersion":5}')
            for info in source.infolist():
                if info.filename != "olca-schema.json":
                    target.writestr(info, source.read(info.filename))

        preview = preview_interchange(output.getvalue())

        self.assertEqual(preview["format"], "openlca-json-ld")
        self.assertEqual(preview["summary"]["model"], 1)

    def test_export_rejects_missing_reference_closure(self):
        self.bundle["flow_properties"] = []
        with self.assertRaises(InterchangeError) as raised:
            export_openlca(self.bundle)
        self.assertEqual(raised.exception.code, "UNRESOLVED_DATASET_REFERENCE")

    def test_import_rejects_parent_traversal(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("olca-schema.json", '{"version":2}')
            archive.writestr("../processes/escape.json", "{}")
        with self.assertRaises(InterchangeError) as raised:
            preview_openlca(output.getvalue())
        self.assertEqual(raised.exception.code, "UNSAFE_ARCHIVE_PATH")


if __name__ == "__main__":
    unittest.main()
