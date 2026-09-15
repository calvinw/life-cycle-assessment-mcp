import copy
import io
import json
import unittest
import zipfile

from lca_core.interchange import (
    InterchangeError,
    export_ilcd,
    export_openlca,
    preview_ilcd,
    preview_openlca,
)
from lca_core.interchange.bundle import prepare_export_bundle
from tests.test_openlca_interchange import OpenLcaInterchangeTests


def _multi_process_bundle():
    baseline = OpenLcaInterchangeTests(methodName="runTest")
    baseline.setUp()
    bundle = copy.deepcopy(baseline.bundle)

    contact_id = "10000000-0000-4000-8000-000000000001"
    source_id = "10000000-0000-4000-8000-000000000002"
    downstream_id = "10000000-0000-4000-8000-000000000003"
    unrelated_id = "10000000-0000-4000-8000-000000000004"
    bundle["contacts"] = [{
        "id": contact_id,
        "type": "contact",
        "name": "PRISM team",
        "description": "Dataset owner",
        "payload": {
            "contactInformation": {"dataSetInformation": {
                "shortName": [{"lang": "en", "text": "PRISM"}],
                "name": [{"lang": "en", "text": "PRISM team"}],
                "email": "prism@example.test",
                "wwwAddress": "https://example.test",
                "classification": [],
                "generalComment": [],
            }},
            "administrativeInformation": {"dataSetVersion": "01.01.000"},
        },
    }]
    bundle["sources"] = [{
        "id": source_id,
        "type": "source",
        "name": "Example source",
        "description": "Source description",
        "payload": {
            "sourceInformation": {"dataSetInformation": {
                "shortName": [{"lang": "en", "text": "Example source"}],
                "classification": [],
                "sourceCitation": "Example citation",
                "publicationType": "Other unpublished and grey literature",
                "sourceDescriptionOrComment": [{"lang": "en", "text": "Source description"}],
                "referenceToContact": {"type": "contact", "refObjectId": contact_id, "shortDescription": "PRISM team"},
            }},
            "administrativeInformation": {"dataSetVersion": "01.01.000"},
        },
    }]

    upstream = bundle["processes"][0]
    upstream["payload"]["modellingAndValidation"]["referenceToDataSource"] = {
        "type": "source", "refObjectId": source_id, "shortDescription": "Example source"
    }
    upstream["payload"]["administrativeInformation"]["referenceToPersonOrEntityGeneratingTheDataSet"] = {
        "type": "contact", "refObjectId": contact_id, "shortDescription": "PRISM team"
    }

    downstream = copy.deepcopy(upstream)
    downstream["id"] = downstream_id
    downstream["name"] = "Steel finishing"
    downstream["description"] = "Finishes steel"
    downstream["payload"]["processInformation"]["dataSetInformation"]["name"]["baseName"][0]["text"] = "Steel finishing"
    downstream["payload"]["processInformation"]["quantitativeReference"]["referenceToReferenceFlow"] = 2
    downstream["payload"]["exchanges"] = [
        {
            "dataSetInternalID": 1,
            "referenceToFlowDataSet": {"type": "flow", "refObjectId": baseline.flow_id, "shortDescription": "Steel"},
            "exchangeDirection": "Input",
            "meanAmount": 1,
            "resultingAmount": 1,
            "generalComment": [],
        },
        {
            "dataSetInternalID": 2,
            "referenceToFlowDataSet": {"type": "flow", "refObjectId": baseline.flow_id, "shortDescription": "Steel"},
            "exchangeDirection": "Output",
            "meanAmount": 1,
            "resultingAmount": 1,
            "generalComment": [],
        },
    ]
    bundle["processes"].append(downstream)
    bundle["processes"].append({
        "id": unrelated_id,
        "type": "process",
        "name": "Unrelated process",
        "description": "Not in the selected Model",
        "payload": {"processInformation": {"dataSetInformation": {}, "quantitativeReference": {"referenceToReferenceFlow": None}}, "exchanges": []},
    })

    model = bundle["models"][0]
    model["payload"]["processInstances"] = [
        model["payload"]["processInstances"][0],
        {
            "dataSetInternalID": 2,
            "referenceToProcess": {"type": "process", "refObjectId": downstream_id, "shortDescription": "Steel finishing"},
            "multiplicationFactor": 2,
        },
    ]
    model["payload"]["connections"] = [{"fromInstanceId": 1, "toInstanceId": 2}]
    return bundle, baseline.model_id, unrelated_id


class InterchangeExportTests(unittest.TestCase):
    def test_model_selection_includes_transitive_closure_only(self):
        bundle, model_id, unrelated_id = _multi_process_bundle()

        selected = prepare_export_bundle(bundle, model_id)

        selected_ids = {row["id"] for rows in selected.values() for row in rows}
        self.assertNotIn(unrelated_id, selected_ids)
        self.assertEqual(len(selected["models"]), 1)
        self.assertEqual(len(selected["processes"]), 2)
        self.assertEqual(len(selected["flows"]), 1)
        self.assertEqual(len(selected["flow_properties"]), 1)
        self.assertEqual(len(selected["unit_groups"]), 1)
        self.assertEqual(len(selected["sources"]), 1)
        self.assertEqual(len(selected["contacts"]), 1)

    def test_openlca_model_selection_omits_unrelated_records(self):
        bundle, model_id, unrelated_id = _multi_process_bundle()

        package = export_openlca(bundle, model_id)

        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertNotIn(f"processes/{unrelated_id}.json", archive.namelist())
            system = json.loads(
                archive.read(f"product_systems/{model_id}.json")
            )
        self.assertEqual(len(system["processes"]), 2)
        self.assertEqual(len(system["processLinks"]), 1)
        preview = preview_openlca(package)
        model = next(row for row in preview["datasets"] if row["type"] == "model")
        self.assertEqual(
            model["payload"]["connections"],
            [{"fromInstanceId": 1, "toInstanceId": 2}],
        )

    def test_missing_selected_dependency_fails_atomically(self):
        bundle, model_id, _ = _multi_process_bundle()
        bundle["flows"] = []

        with self.assertRaises(InterchangeError) as raised:
            export_openlca(bundle, model_id)

        self.assertEqual(raised.exception.code, "UNRESOLVED_DATASET_REFERENCE")

    def test_ilcd_export_is_deterministic_and_round_trips_graph(self):
        bundle, model_id, unrelated_id = _multi_process_bundle()

        first = export_ilcd(bundle, model_id)
        second = export_ilcd(bundle, model_id)
        self.assertEqual(first, second)

        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertNotIn(f"ILCD/processes/{unrelated_id}.xml", archive.namelist())
            source_xml = archive.read(
                "ILCD/sources/10000000-0000-4000-8000-000000000002.xml"
            ).decode("utf-8")
            contact_xml = archive.read(
                "ILCD/contacts/10000000-0000-4000-8000-000000000001.xml"
            ).decode("utf-8")
        self.assertIn("<common:shortName", source_xml)
        self.assertIn("<common:shortName", contact_xml)
        self.assertIn("<common:name", contact_xml)
        self.assertIn("<c:contactDescriptionOrComment", contact_xml)

        preview = preview_ilcd(first)
        self.assertEqual(preview["summary"], {
            "model": 1,
            "process": 2,
            "flow": 1,
            "flow_property": 1,
            "unit_group": 1,
            "source": 1,
            "contact": 1,
        })
        rows = {row["id"]: row for row in preview["datasets"]}
        model = rows[model_id]
        self.assertEqual(model["payload"]["connections"], [{"fromInstanceId": 1, "toInstanceId": 2}])
        self.assertEqual(model["payload"]["processInstances"][1]["multiplicationFactor"], 2.0)
        source = next(row for row in preview["datasets"] if row["type"] == "source")
        self.assertEqual(
            source["payload"]["sourceInformation"]["dataSetInformation"]["sourceCitation"],
            "Example citation",
        )


if __name__ == "__main__":
    unittest.main()
