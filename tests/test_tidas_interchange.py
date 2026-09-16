import io
import json
import unittest
import uuid
import zipfile
from pathlib import Path

from lca_core.interchange import (
    InterchangeError,
    export_tidas,
    preview_interchange,
    preview_tidas,
)

FIXTURE_NO_MODEL = Path(__file__).parent / "fixtures" / "tidas_tiangong_export.zip"
FIXTURE_WITH_MODEL = Path(__file__).parent / "fixtures" / "tidas_tiangong_export_with_model.zip"


def _id() -> str:
    return str(uuid.uuid4())


def _two_process_model_bundle() -> tuple[dict, str]:
    """A synthetic PRISM bundle: two Processes linked by one Model.

    This mirrors the fixture actually round-tripped through the real
    Tiangong platform while building the TIDAS export support (see
    TIDAS_IMPORT_EXPORT_PLAN.md) — kept here so the export-side schema
    requirements it exercises (forced arrays, `@version` on connections,
    per-type classification shape, etc.) stay covered by an automated test.
    """
    unit_group_id, flow_property_id, flow_id = _id(), _id(), _id()
    process_a_id, process_b_id, model_id = _id(), _id(), _id()

    bundle = {
        "unit_groups": [
            {
                "id": unit_group_id,
                "type": "unit_group",
                "name": "Units of mass",
                "description": "Mass units",
                "payload": {
                    "unitGroupInformation": {
                        "dataSetInformation": {
                            "name": [{"lang": "en", "text": "Units of mass"}],
                            "classification": [],
                            "generalComment": [],
                        },
                        "quantitativeReference": {"referenceToReferenceUnit": 1},
                    },
                    "units": [
                        {"dataSetInternalID": 1, "name": "kg", "meanValue": 1, "generalComment": []}
                    ],
                    "administrativeInformation": {"dataSetVersion": "01.01.000"},
                },
            }
        ],
        "flow_properties": [
            {
                "id": flow_property_id,
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
                                "refObjectId": unit_group_id,
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
                "id": flow_id,
                "type": "flow",
                "name": "Intermediate steel sheet",
                "description": "Flow connecting the two processes",
                "payload": {
                    "flowInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [{"lang": "en", "text": "Intermediate steel sheet"}],
                                "treatmentStandardsRoutes": [],
                                "mixAndLocationTypes": [],
                            },
                            "classification": [],
                            "generalComment": [],
                        },
                        "quantitativeReference": {"referenceToReferenceFlowProperty": 1},
                    },
                    "modellingAndValidation": {"typeOfDataSet": "Product flow"},
                    "flowProperties": [
                        {
                            "dataSetInternalID": 1,
                            "referenceToFlowPropertyDataSet": {
                                "type": "flow_property",
                                "refObjectId": flow_property_id,
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
                "id": process_a_id,
                "type": "process",
                "name": "Steel production",
                "description": "Upstream: produces the intermediate steel sheet",
                "payload": {
                    "processInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [{"lang": "en", "text": "Steel production"}],
                                "treatmentStandardsRoutes": [],
                                "mixAndLocationTypes": [],
                            },
                            "classification": [],
                            "generalComment": [],
                        },
                        "quantitativeReference": {"referenceToReferenceFlow": 1},
                        "geography": {"location": "GLO"},
                    },
                    "modellingAndValidation": {"typeOfDataSet": "Unit process, single operation"},
                    "administrativeInformation": {"dataSetVersion": "01.01.000"},
                    "exchanges": [
                        {
                            "dataSetInternalID": 1,
                            "referenceToFlowDataSet": {
                                "type": "flow",
                                "refObjectId": flow_id,
                                "shortDescription": "Intermediate steel sheet",
                            },
                            "exchangeDirection": "Output",
                            "meanAmount": 1,
                            "resultingAmount": 1,
                            "generalComment": [],
                        }
                    ],
                },
            },
            {
                "id": process_b_id,
                "type": "process",
                "name": "Steel finishing",
                "description": "Downstream: consumes the intermediate steel sheet",
                "payload": {
                    "processInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [{"lang": "en", "text": "Steel finishing"}],
                                "treatmentStandardsRoutes": [],
                                "mixAndLocationTypes": [],
                            },
                            "classification": [],
                            "generalComment": [],
                        },
                        "quantitativeReference": {"referenceToReferenceFlow": 2},
                        "geography": {"location": "GLO"},
                    },
                    "modellingAndValidation": {"typeOfDataSet": "Unit process, single operation"},
                    "administrativeInformation": {"dataSetVersion": "01.01.000"},
                    "exchanges": [
                        {
                            "dataSetInternalID": 1,
                            "referenceToFlowDataSet": {
                                "type": "flow",
                                "refObjectId": flow_id,
                                "shortDescription": "Intermediate steel sheet",
                            },
                            "exchangeDirection": "Input",
                            "meanAmount": 1,
                            "resultingAmount": 1,
                            "generalComment": [],
                        },
                        {
                            "dataSetInternalID": 2,
                            "referenceToFlowDataSet": {
                                "type": "flow",
                                "refObjectId": flow_id,
                                "shortDescription": "Finished steel product",
                            },
                            "exchangeDirection": "Output",
                            "meanAmount": 1,
                            "resultingAmount": 1,
                            "generalComment": [],
                        },
                    ],
                },
            },
        ],
        "models": [
            {
                "id": model_id,
                "type": "model",
                "name": "Steel system (two processes)",
                "description": "Synthetic model for TIDAS round-trip testing via Tiangong",
                "payload": {
                    "modelInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [{"lang": "en", "text": "Steel system (two processes)"}],
                                "treatmentStandardsRoutes": [],
                                "mixAndLocationTypes": [],
                            },
                            "classification": [],
                            "generalComment": [],
                        },
                        "quantitativeReference": {"referenceToReferenceProcess": 2},
                    },
                    "processInstances": [
                        {
                            "dataSetInternalID": 1,
                            "referenceToProcess": {
                                "type": "process",
                                "refObjectId": process_a_id,
                                "shortDescription": "Steel production",
                            },
                            "multiplicationFactor": 1,
                        },
                        {
                            "dataSetInternalID": 2,
                            "referenceToProcess": {
                                "type": "process",
                                "refObjectId": process_b_id,
                                "shortDescription": "Steel finishing",
                            },
                            "multiplicationFactor": 1,
                        },
                    ],
                    "connections": [{"fromInstanceId": 1, "toInstanceId": 2}],
                    "administrativeInformation": {"dataSetVersion": "01.01.000"},
                },
            }
        ],
        "sources": [],
        "contacts": [],
    }
    return bundle, model_id


class TidasImportTests(unittest.TestCase):
    def test_real_tiangong_export_without_model_is_converted(self):
        preview = preview_tidas(FIXTURE_NO_MODEL.read_bytes())

        self.assertEqual(preview["format"], "tidas-json")
        self.assertTrue(preview["valid"])
        self.assertEqual(
            preview["summary"],
            {
                "model": 0,
                "process": 18,
                "flow": 31,
                "flow_property": 4,
                "unit_group": 4,
                "source": 3,
                "contact": 3,
            },
        )
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(preview["errors"], [])

    def test_real_tiangong_export_with_model_flattens_graph(self):
        """The one real Tiangong export that actually contains a populated
        lifecyclemodels/ entry — see TIDAS_IMPORT_EXPORT_PLAN.md for how it
        was obtained (round-tripped through the real platform). This is the
        only test that exercises the Model graph-flattening path against
        real data rather than a synthetic fixture.
        """
        preview = preview_tidas(FIXTURE_WITH_MODEL.read_bytes())

        self.assertEqual(
            preview["summary"],
            {
                "model": 1,
                "process": 20,
                "flow": 32,
                "flow_property": 5,
                "unit_group": 5,
                "source": 3,
                "contact": 3,
            },
        )
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(preview["errors"], [])

        model = next(row for row in preview["datasets"] if row["type"] == "model")
        self.assertEqual(model["name"], "Steel system (two processes)")
        self.assertEqual(model["payload"]["connections"], [{"fromInstanceId": 1, "toInstanceId": 2}])
        self.assertEqual(
            model["payload"]["modelInformation"]["quantitativeReference"]["referenceToReferenceProcess"], 2
        )
        instances = model["payload"]["processInstances"]
        self.assertEqual(len(instances), 2)
        self.assertEqual(instances[0]["dataSetInternalID"], 1)
        self.assertEqual(instances[1]["dataSetInternalID"], 2)

    def test_dispatch_detects_tidas_via_manifest(self):
        preview = preview_interchange(FIXTURE_NO_MODEL.read_bytes())
        self.assertEqual(preview["format"], "tidas-json")

    def test_tolerates_extra_top_level_sibling_key(self):
        """A real Tiangong export can carry `{"json_tg": {}, "<root>": {...}}`
        — confirmed in tests/fixtures/tidas_tiangong_export_with_model.zip.
        Build a minimal package reproducing just that shape.
        """
        flow_id = _id()
        manifest = {
            "format": "tiangong-tidas-package",
            "version": 2,
            "entries": [{"table": "flows", "id": flow_id, "version": "01.01.000", "file_path": f"flows/{flow_id}.json"}],
        }
        flow_doc = {
            "json_tg": {},
            "flowDataSet": {
                "flowInformation": {
                    "dataSetInformation": {"common:UUID": flow_id, "name": {"baseName": "Test flow"}},
                    "quantitativeReference": {"referenceToReferenceFlowProperty": "1"},
                }
            },
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr(f"flows/{flow_id}.json", json.dumps(flow_doc))

        preview = preview_tidas(output.getvalue())
        self.assertEqual(preview["summary"]["flow"], 1)
        # The synthetic flow has no flowProperties, so an
        # UNRESOLVED_DATASET_REFERENCE warning is expected here; the point
        # of this test is that the extra "json_tg" sibling key doesn't blow
        # up parsing, not that this minimal flow is fully cross-referenced.
        codes = {item["code"] for item in preview["warnings"]}
        self.assertEqual(codes, {"UNRESOLVED_DATASET_REFERENCE"})

    def test_missing_manifest_falls_back_to_folder_scan_with_warning(self):
        flow_id = _id()
        flow_doc = {
            "flowDataSet": {
                "flowInformation": {
                    "dataSetInformation": {"common:UUID": flow_id, "name": {"baseName": "Test flow"}},
                    "quantitativeReference": {"referenceToReferenceFlowProperty": "1"},
                }
            }
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(f"flows/{flow_id}.json", json.dumps(flow_doc))

        preview = preview_tidas(output.getvalue())
        self.assertEqual(preview["summary"]["flow"], 1)
        codes = {item["code"] for item in preview["warnings"]}
        self.assertIn("TIDAS_MISSING_MANIFEST", codes)

    def test_missing_manifest_reachable_through_dispatcher(self):
        """The folder-scan fallback above must be reachable through the real
        import entry point (`preview_interchange`), not just via a direct
        `preview_tidas` call — a manifest-less package is still a valid
        signal on its own (a known dataset folder holding `.json` members).
        """
        flow_id = _id()
        flow_doc = {
            "flowDataSet": {
                "flowInformation": {
                    "dataSetInformation": {"common:UUID": flow_id, "name": {"baseName": "Test flow"}},
                    "quantitativeReference": {"referenceToReferenceFlowProperty": "1"},
                }
            }
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(f"flows/{flow_id}.json", json.dumps(flow_doc))

        preview = preview_interchange(output.getvalue())
        self.assertEqual(preview["format"], "tidas-json")
        codes = {item["code"] for item in preview["warnings"]}
        self.assertIn("TIDAS_MISSING_MANIFEST", codes)

    def test_unrelated_manifest_json_does_not_shadow_root_level_ilcd(self):
        """A root-of-zip ILCD package (.xml, not .json) that happens to also
        carry an unrelated manifest.json (some other tool's export) must not
        be misrouted into TIDAS parsing just because a file named
        manifest.json exists.
        """
        flow_id = _id()
        xml = (
            '<?xml version="1.0"?>'
            '<flowDataSet xmlns="http://lca.jrc.it/ILCD/Flow" '
            'xmlns:common="http://lca.jrc.it/ILCD/Common">'
            "<flowInformation><dataSetInformation>"
            f"<common:UUID>{flow_id}</common:UUID>"
            '<name><baseName xml:lang="en">Test flow</baseName></name>'
            "</dataSetInformation>"
            "<quantitativeReference>"
            "<referenceToReferenceFlowProperty>1</referenceToReferenceFlowProperty>"
            "</quantitativeReference>"
            "</flowInformation></flowDataSet>"
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(f"flows/{flow_id}.xml", xml)
            archive.writestr("manifest.json", json.dumps({"format": "some-other-tool"}))

        preview = preview_interchange(output.getvalue())
        self.assertEqual(preview["format"], "ilcd-xml")

    def test_empty_package_is_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"format": "tiangong-tidas-package", "entries": []}))
        with self.assertRaises(InterchangeError) as ctx:
            preview_tidas(output.getvalue())
        self.assertEqual(ctx.exception.code, "EMPTY_TIDAS_PACKAGE")

    def test_duplicate_dataset_id_is_rejected(self):
        flow_id = _id()
        flow_doc = {
            "flowDataSet": {
                "flowInformation": {
                    "dataSetInformation": {"common:UUID": flow_id, "name": {"baseName": "Test flow"}},
                    "quantitativeReference": {"referenceToReferenceFlowProperty": "1"},
                }
            }
        }
        manifest = {
            "format": "tiangong-tidas-package",
            "entries": [
                {"table": "flows", "id": flow_id, "version": "01.01.000", "file_path": "flows/a.json"},
                {"table": "flows", "id": flow_id, "version": "01.01.000", "file_path": "flows/b.json"},
            ],
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("flows/a.json", json.dumps(flow_doc))
            archive.writestr("flows/b.json", json.dumps(flow_doc))
        with self.assertRaises(InterchangeError) as ctx:
            preview_tidas(output.getvalue())
        self.assertEqual(ctx.exception.code, "DUPLICATE_TIDAS_ID")


class TidasExportTests(unittest.TestCase):
    def test_export_is_deterministic(self):
        bundle, model_id = _two_process_model_bundle()
        first = export_tidas(bundle, model_id)
        second = export_tidas(bundle, model_id)
        self.assertEqual(first, second)

    def test_export_round_trips_through_own_importer(self):
        bundle, model_id = _two_process_model_bundle()
        package = export_tidas(bundle, model_id)

        preview = preview_tidas(package)
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
        self.assertEqual(preview["warnings"], [])
        self.assertEqual(preview["errors"], [])

        model = next(row for row in preview["datasets"] if row["type"] == "model")
        self.assertEqual(model["payload"]["connections"], [{"fromInstanceId": 1, "toInstanceId": 2}])

    def test_export_includes_manifest_with_correct_counts(self):
        bundle, model_id = _two_process_model_bundle()
        package = export_tidas(bundle, model_id)

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))

        self.assertEqual(manifest["format"], "tiangong-tidas-package")
        self.assertEqual(
            manifest["counts"],
            {
                "lifecyclemodels": 1,
                "processes": 2,
                "flows": 1,
                "flowproperties": 1,
                "unitgroups": 1,
                "sources": 0,
                "contacts": 0,
            },
        )
        self.assertEqual(manifest["total_count"], 6)
        paths = {entry["file_path"] for entry in manifest["entries"]}
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            zip_paths = set(archive.namelist()) - {"manifest.json"}
        self.assertEqual(paths, zip_paths)

    def test_exchanges_and_process_instances_are_always_arrays(self):
        """Confirmed by a real Tiangong validation report: `exchanges.exchange`
        and `technology.processes.processInstance` must be JSON arrays even
        with a single item, not a bare object.
        """
        bundle, model_id = _two_process_model_bundle()
        package = export_tidas(bundle, model_id)

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            for name in archive.namelist():
                if not name.startswith("processes/"):
                    continue
                doc = json.loads(archive.read(name))
                exchanges = doc["processDataSet"]["exchanges"]["exchange"]
                self.assertIsInstance(exchanges, list)
            for name in archive.namelist():
                if not name.startswith("lifecyclemodels/"):
                    continue
                doc = json.loads(archive.read(name))
                instances = doc["lifeCycleModelDataSet"]["lifeCycleModelInformation"]["technology"][
                    "processes"
                ]["processInstance"]
                self.assertIsInstance(instances, list)

    def test_model_connections_carry_required_version_attribute(self):
        """`outputExchange`/`downstreamProcess` both require `@version` per
        Tiangong's real schema (tidas_lifecyclemodels.json) — missing it was
        the root cause of a persistent anyOf failure across several rounds
        of validation before this was found by reading the schema directly.
        """
        bundle, model_id = _two_process_model_bundle()
        package = export_tidas(bundle, model_id)

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            model_path = next(n for n in archive.namelist() if n.startswith("lifecyclemodels/"))
            doc = json.loads(archive.read(model_path))
        instances = doc["lifeCycleModelDataSet"]["lifeCycleModelInformation"]["technology"]["processes"][
            "processInstance"
        ]
        connections = instances[0]["connections"]["outputExchange"]
        self.assertIn("@version", connections)
        self.assertIn("@version", connections["downstreamProcess"])

    def test_unit_group_classification_is_a_bare_object_not_array(self):
        """Confirmed from tidas_unitgroups.json: unlike Process/Flow/Model,
        UnitGroup's (and FlowProperty's) `common:class` is a single object,
        not an array.
        """
        bundle, model_id = _two_process_model_bundle()
        package = export_tidas(bundle, model_id)

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            ug_path = next(n for n in archive.namelist() if n.startswith("unitgroups/"))
            doc = json.loads(archive.read(ug_path))
        class_node = doc["unitGroupDataSet"]["unitGroupInformation"]["dataSetInformation"][
            "classificationInformation"
        ]["common:classification"]["common:class"]
        self.assertIsInstance(class_node, dict)

    def test_dispatch_routes_tidas_json_format(self):
        from lca_core.interchange.exporter import export_interchange

        bundle, model_id = _two_process_model_bundle()
        package = export_interchange("tidas-json", bundle, model_id)
        preview = preview_tidas(package)
        self.assertEqual(preview["summary"]["model"], 1)


if __name__ == "__main__":
    unittest.main()
