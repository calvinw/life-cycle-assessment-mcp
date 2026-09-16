import io
import unittest
import uuid
import zipfile
from pathlib import Path

from lca_core.interchange import InterchangeError, preview_ilcd, preview_interchange


FIXTURE = Path(__file__).parent / "fixtures" / "ilcd_plastic_broom.zip"


def _zip(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ILCD/", "")
        for path, value in entries.items():
            archive.writestr(path, value)
    return output.getvalue()


class IlcdInterchangeTests(unittest.TestCase):
    def test_real_openlca_desktop_export_is_converted(self):
        preview = preview_ilcd(FIXTURE.read_bytes())

        self.assertEqual(preview["format"], "ilcd-xml")
        self.assertTrue(preview["valid"])
        self.assertEqual(
            preview["summary"],
            {
                "model": 1,
                "process": 4,
                "flow": 6,
                "flow_property": 0,
                "unit_group": 4,
                "source": 0,
                "contact": 0,
            },
        )
        ignored = [item for item in preview["warnings"] if item["code"] == "UNSUPPORTED_PACKAGE_ENTRY"]
        self.assertEqual(len(ignored), 2)

    def test_real_export_preserves_fields_and_flattens_model_graph(self):
        preview = preview_ilcd(FIXTURE.read_bytes())
        rows = {row["id"]: row for row in preview["datasets"]}

        process = rows["de1244ea-4510-53c8-b5be-5205ed78e3b7"]
        self.assertEqual(process["name"], "Mock polypropylene granulate, at plant")
        self.assertEqual(process["payload"]["processInformation"]["geography"]["location"], "MOCK")
        self.assertEqual(process["payload"]["exchanges"][1]["meanAmount"], 2.0)
        self.assertEqual(
            process["payload"]["exchanges"][1]["referenceToFlowDataSet"]["refObjectId"],
            "03f77556-180f-5715-9b0e-9c315efac2ef",
        )

        unit_group = rows["93a60a57-a3c8-11da-a746-0800200c9a66"]
        self.assertEqual(unit_group["payload"]["units"][0]["name"], "kWh")
        self.assertEqual(unit_group["payload"]["units"][0]["meanValue"], 1.0)

        model = rows["69041a0d-d81e-5c22-8b99-184707883d1e"]
        self.assertEqual(
            model["payload"]["connections"],
            [
                {"fromInstanceId": 2, "toInstanceId": 3},
                {"fromInstanceId": 1, "toInstanceId": 0},
                {"fromInstanceId": 1, "toInstanceId": 2},
                {"fromInstanceId": 0, "toInstanceId": 3},
            ],
        )

    def test_dispatch_detects_ilcd(self):
        preview = preview_interchange(FIXTURE.read_bytes())
        self.assertEqual(preview["format"], "ilcd-xml")

    def test_manifestless_hybrid_package_uses_its_ilcd_representation(self):
        flow_id = str(uuid.uuid4())
        package = _zip(
            {
                f"ILCD/flows/{flow_id}.xml": f"""<flowDataSet>
                    <flowInformation><dataSetInformation><UUID>{flow_id}</UUID>
                    <name><baseName>Hybrid flow</baseName></name>
                    </dataSetInformation></flowInformation></flowDataSet>""",
                f"flows/{flow_id}.json": "{}",
            }
        )

        preview = preview_interchange(package)

        self.assertEqual(preview["format"], "ilcd-xml")
        self.assertEqual(preview["summary"]["flow"], 1)
        self.assertIn(
            "HYBRID_ILCD_OPENLCA_PACKAGE",
            {warning["code"] for warning in preview["warnings"]},
        )

    def test_root_of_zip_layout_without_ilcd_wrapper_is_accepted(self):
        """Some platforms (e.g. Tiangong's documented ZIP upload convention)
        expect dataset folders directly at the ZIP root, no "ILCD/" wrapper
        — see `has_root_level_ilcd_layout`'s docstring.
        """
        flow_id = str(uuid.uuid4())
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                f"flows/{flow_id}.xml",
                f"""<flowDataSet>
                    <flowInformation><dataSetInformation><UUID>{flow_id}</UUID>
                    <name><baseName>Root-of-zip flow</baseName></name>
                    </dataSetInformation></flowInformation></flowDataSet>""",
            )

        preview = preview_interchange(output.getvalue())

        self.assertEqual(preview["format"], "ilcd-xml")
        self.assertEqual(preview["summary"]["flow"], 1)
        self.assertEqual(preview["datasets"][0]["name"], "Root-of-zip flow")

    def test_dispatch_rejects_unknown_zip_layout(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("unknown.txt", "not an interchange package")
        with self.assertRaises(InterchangeError) as raised:
            preview_interchange(output.getvalue())
        self.assertEqual(raised.exception.code, "UNSUPPORTED_PACKAGE_FORMAT")
        self.assertEqual(raised.exception.status_code, 400)

    def test_malformed_xml_is_rejected(self):
        package = _zip({"ILCD/flows/broken.xml": "<flowDataSet>"})
        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)
        self.assertEqual(raised.exception.code, "INVALID_ILCD_XML")

    def test_xml_entity_declarations_are_rejected(self):
        package = _zip(
            {
                "ILCD/flows/broken.xml": """<!DOCTYPE x [<!ENTITY x 'unsafe'>]>
                    <flowDataSet><flowInformation><dataSetInformation>
                    <UUID>&x;</UUID></dataSetInformation></flowInformation></flowDataSet>"""
            }
        )
        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)
        self.assertEqual(raised.exception.code, "INVALID_ILCD_XML")

    def test_missing_uuid_is_rejected(self):
        package = _zip(
            {
                "ILCD/flows/missing.xml": """<flowDataSet>
                    <flowInformation><dataSetInformation><name><baseName>Missing</baseName></name>
                    </dataSetInformation></flowInformation></flowDataSet>"""
            }
        )
        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)
        self.assertEqual(raised.exception.code, "MISSING_ILCD_UUID")

    def test_invalid_uuid_is_rejected(self):
        package = _zip(
            {
                "ILCD/flows/not-a-uuid.xml": """<flowDataSet>
                    <flowInformation><dataSetInformation><UUID>not-a-uuid</UUID>
                    <name><baseName>Invalid</baseName></name>
                    </dataSetInformation></flowInformation></flowDataSet>"""
            }
        )
        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)
        self.assertEqual(raised.exception.code, "INVALID_ILCD_UUID")

    def test_unresolved_model_process_is_a_hard_error(self):
        model_id = str(uuid.uuid4())
        missing_process_id = str(uuid.uuid4())
        package = _zip(
            {
                f"ILCD/lifecyclemodels/{model_id}.xml": f"""<lifeCycleModelDataSet>
                  <lifeCycleModelInformation><dataSetInformation><UUID>{model_id}</UUID>
                  <name><baseName>Broken model</baseName></name></dataSetInformation>
                  <quantitativeReference><referenceToReferenceProcess>1</referenceToReferenceProcess></quantitativeReference>
                  <technology><processes><processInstance dataSetInternalID="1">
                  <referenceToProcess refObjectId="{missing_process_id}" />
                  </processInstance></processes></technology></lifeCycleModelInformation>
                </lifeCycleModelDataSet>"""
            }
        )
        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)
        self.assertEqual(raised.exception.code, "UNRESOLVED_DATASET_REFERENCE")

    def test_flow_property_source_and_contact_are_converted(self):
        unit_group_id = str(uuid.uuid4())
        flow_property_id = str(uuid.uuid4())
        source_id = str(uuid.uuid4())
        contact_id = str(uuid.uuid4())
        package = _zip(
            {
                f"ILCD/unitgroups/{unit_group_id}.xml": f"""<unitGroupDataSet>
                  <unitGroupInformation><dataSetInformation><UUID>{unit_group_id}</UUID>
                  <name xml:lang="en">Mass units</name></dataSetInformation>
                  <quantitativeReference><referenceToReferenceUnit>1</referenceToReferenceUnit></quantitativeReference>
                  </unitGroupInformation><units><unit dataSetInternalID="1"><name>kg</name><meanValue>1</meanValue></unit></units>
                </unitGroupDataSet>""",
                f"ILCD/flowproperties/{flow_property_id}.xml": f"""<flowPropertyDataSet>
                  <flowPropertiesInformation><dataSetInformation><UUID>{flow_property_id}</UUID>
                  <name xml:lang="en">Mass</name></dataSetInformation>
                  <quantitativeReference><referenceToReferenceUnitGroup refObjectId="{unit_group_id}">
                  <shortDescription xml:lang="en">Mass units</shortDescription></referenceToReferenceUnitGroup>
                  </quantitativeReference></flowPropertiesInformation>
                </flowPropertyDataSet>""",
                f"ILCD/contacts/{contact_id}.xml": f"""<contactDataSet>
                  <contactInformation><dataSetInformation><UUID>{contact_id}</UUID>
                  <shortName xml:lang="en">Example Org</shortName><name xml:lang="en">Example Organisation</name>
                  <email>lca@example.test</email><WWWAddress>https://example.test</WWWAddress>
                  </dataSetInformation></contactInformation></contactDataSet>""",
                f"ILCD/sources/{source_id}.xml": f"""<sourceDataSet>
                  <sourceInformation><dataSetInformation><UUID>{source_id}</UUID>
                  <shortName xml:lang="en">Example source</shortName><sourceCitation>Example citation</sourceCitation>
                  <sourceDescriptionOrComment xml:lang="en">Source details</sourceDescriptionOrComment>
                  <referenceToContact refObjectId="{contact_id}"><shortDescription xml:lang="en">Example Org</shortDescription></referenceToContact>
                  </dataSetInformation></sourceInformation></sourceDataSet>""",
            }
        )

        preview = preview_ilcd(package)
        rows = {row["id"]: row for row in preview["datasets"]}
        self.assertEqual(preview["summary"]["flow_property"], 1)
        self.assertEqual(preview["summary"]["source"], 1)
        self.assertEqual(preview["summary"]["contact"], 1)
        reference = rows[flow_property_id]["payload"]["flowPropertiesInformation"]["quantitativeReference"]["referenceToReferenceUnitGroup"]
        self.assertEqual(reference["refObjectId"], unit_group_id)
        self.assertEqual(rows[source_id]["payload"]["sourceInformation"]["dataSetInformation"]["sourceCitation"], "Example citation")
        self.assertEqual(rows[source_id]["description"], "Source details")
        contact = rows[contact_id]["payload"]["contactInformation"]["dataSetInformation"]
        self.assertEqual(contact["shortName"], [{"lang": "en", "text": "Example Org"}])
        self.assertEqual(contact["name"], [{"lang": "en", "text": "Example Organisation"}])
        self.assertEqual(contact["email"], "lca@example.test")
        self.assertEqual(contact["wwwAddress"], "https://example.test")

    def test_duplicate_ids_are_rejected(self):
        dataset_id = str(uuid.uuid4())
        xml = f"""<flowDataSet><flowInformation><dataSetInformation>
            <UUID>{dataset_id}</UUID><name><baseName>Duplicate</baseName></name>
            </dataSetInformation></flowInformation></flowDataSet>"""
        package = _zip(
            {
                f"ILCD/flows/{dataset_id}.xml": xml,
                "ILCD/flows/copy.xml": xml,
            }
        )
        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)
        self.assertEqual(raised.exception.code, "DUPLICATE_ILCD_ID")

    def test_duplicate_model_process_instance_ids_are_rejected(self):
        model_id = str(uuid.uuid4())
        process_id = str(uuid.uuid4())
        process = f"""<processDataSet><processInformation><dataSetInformation>
            <UUID>{process_id}</UUID><name><baseName>Process</baseName></name>
            </dataSetInformation></processInformation></processDataSet>"""
        model = f"""<lifeCycleModelDataSet><lifeCycleModelInformation>
            <dataSetInformation><UUID>{model_id}</UUID><name><baseName>Model</baseName></name></dataSetInformation>
            <quantitativeReference><referenceToReferenceProcess>1</referenceToReferenceProcess></quantitativeReference>
            <technology><processes>
              <processInstance dataSetInternalID="1"><referenceToProcess refObjectId="{process_id}" /></processInstance>
              <processInstance dataSetInternalID="1"><referenceToProcess refObjectId="{process_id}" /></processInstance>
            </processes></technology></lifeCycleModelInformation></lifeCycleModelDataSet>"""
        package = _zip(
            {
                f"ILCD/processes/{process_id}.xml": process,
                f"ILCD/lifecyclemodels/{model_id}.xml": model,
            }
        )

        with self.assertRaises(InterchangeError) as raised:
            preview_ilcd(package)

        self.assertEqual(
            raised.exception.code, "INVALID_ILCD_PROCESS_INSTANCE_ID"
        )


if __name__ == "__main__":
    unittest.main()
