"""PRISM workspace bundle to deterministic TIDAS JSON ZIP export.

Mirrors `ilcd_export.py` field-for-field, producing Badgerfish-style JSON
(see `tidas.py`'s module docstring for the encoding rules) instead of XML.
Where `ilcd_export.py` passes a namespace URI (`ns` vs `COMMON_NS`) to decide
which XML namespace an element belongs to, this module instead prefixes the
JSON key with `common:` — that mapping was derived directly from
`ilcd_export.py`'s existing `COMMON_NS`/`ns` call sites, not re-derived from
scratch, so the two stay in sync if the ILCD field mapping ever changes.

Also emits `manifest.json` (the Tiangong-authored index format confirmed
from a real export — see `TIDAS_IMPORT_EXPORT_PLAN.md`) so a round-trip
through `tidas.py`'s importer, or through the Tiangong platform itself,
resolves files the same way Tiangong's own exports do.

The required-field set below (xsi/schemaLocation attributes, `validation`,
`complianceDeclarations`, the full `common:*` administrativeInformation
fields, `dataDerivationTypeStatus`, forced-array `exchange`/`processInstance`,
integer-typed internal-reference fields, `@uri` on every reference) is not
derived from ILCD's own spec — it was reverse-engineered from a real
Tiangong platform validation report (`VALIDATION_FAILED`, 86 schema errors)
returned after uploading an early version of this export that only followed
`ilcd_export.py`'s XML-era assumptions. Tiangong's JSON Schema is stricter
than bare ILCD XML about which fields are required.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from .archive import write_deterministic_zip
from .bundle import PLURAL_KEYS, prepare_export_bundle
from .errors import InterchangeError
from .ilcd import DATASET_FOLDERS, ROOT_NAMESPACES
from .tidas import TIDAS_MANIFEST_FORMAT

COMMON_NS = "http://lca.jrc.it/ILCD/Common"
_NIL_CONTACT_ID = "00000000-0000-4000-8000-000000000001"
_NIL_SOURCE_ID = "00000000-0000-4000-8000-000000000002"
_NIL_URI = "https://example.invalid/not-specified"

_SCHEMA_LOCATIONS = {
    "model": "../../schemas/ILCD_LifeCycleModelDataSet.xsd",
    "process": "../../schemas/ILCD_ProcessDataSet.xsd",
    "flow": "../../schemas/ILCD_FlowDataSet.xsd",
    "flow_property": "../../schemas/ILCD_FlowPropertyDataSet.xsd",
    "unit_group": "../../schemas/ILCD_UnitGroupDataSet.xsd",
    "source": "../../schemas/ILCD_SourceDataSet.xsd",
    "contact": "../../schemas/ILCD_ContactDataSet.xsd",
}


def export_tidas(bundle: dict[str, Any], model_id: str | None = None) -> bytes:
    """Convert a PRISM bundle into a self-contained TIDAS JSON ZIP."""
    prepared = prepare_export_bundle(bundle, model_id)
    records = [row for plural in PLURAL_KEYS.values() for row in prepared[plural]]
    by_id = {row["id"]: row for row in records}
    entries: dict[str, bytes] = {}
    manifest_entries: list[dict[str, Any]] = []
    counts = {kind: 0 for kind in DATASET_FOLDERS}
    sorted_records = sorted(records, key=lambda item: (item["type"], item["id"]))
    for row in sorted_records:
        root = _serialize(row, by_id)
        folder = DATASET_FOLDERS[row["type"]][0]
        version = _dig(row, "payload", "administrativeInformation", "dataSetVersion") or "01.01.000"
        file_path = f"{folder}/{row['id']}_{version}.json"
        entries[file_path] = json.dumps(
            root, ensure_ascii=False, separators=(",", ":"), sort_keys=False
        ).encode("utf-8")
        manifest_entries.append(
            {
                "table": folder,
                "id": row["id"],
                "version": version,
                "file_path": file_path,
                "rule_verification": True,
            }
        )
        counts[row["type"]] += 1
    manifest = {
        "format": TIDAS_MANIFEST_FORMAT,
        "version": 2,
        "scope": "prism_export",
        "roots": [
            {"table": DATASET_FOLDERS[row["type"]][0], "id": row["id"], "version": _dig(row, "payload", "administrativeInformation", "dataSetVersion") or "01.01.000"}
            for row in sorted_records
            if row["type"] == "model"
        ],
        "entries": sorted(manifest_entries, key=lambda item: item["file_path"]),
        "counts": {DATASET_FOLDERS[kind][0]: count for kind, count in counts.items()},
        "total_count": sum(counts.values()),
    }
    entries["manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=False
    ).encode("utf-8")
    return write_deterministic_zip(entries)


def _serialize(row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    kind = row["type"]
    namespace = ROOT_NAMESPACES[kind]
    root_name = DATASET_FOLDERS[kind][1]
    root: dict[str, Any] = {
        "@xmlns": namespace,
        "@xmlns:common": COMMON_NS,
        "@xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "@version": "1.1",
        "@locations": "../ILCDLocations.xml",
        "@xsi:schemaLocation": f"{namespace} {_SCHEMA_LOCATIONS[kind]}",
    }
    if kind == "flow":
        root["@xmlns:ecn"] = "http://eplca.jrc.ec.europa.eu/ILCD/Extensions/2018/ECNumber"
    if kind == "model":
        root["@xmlns:acme"] = "http://acme.com/custom"
    {
        "unit_group": _unit_group,
        "flow_property": _flow_property,
        "flow": _flow,
        "source": _source,
        "contact": _contact,
        "process": _process,
        "model": _model,
    }[kind](root, row, by_id)
    return {root_name: root}


def _unit_group(root: dict[str, Any], row: dict[str, Any], _: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "unitGroupInformation")
    data = _data_info(information, row, direct_name=True)
    _classification(data, payload, "unitGroupInformation", "unit_group")
    _lang(data, "common:generalComment", row.get("description"))
    quantitative = _sub(information, "quantitativeReference")
    _value(
        quantitative,
        "referenceToReferenceUnit",
        _dig(payload, "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit"),
    )
    modelling = _sub(root, "modellingAndValidation")
    _placeholder_compliance(modelling)
    _admin(root, payload)
    units = _sub_array(root, "units", "unit")
    for item in _dicts(payload.get("units")):
        unit = _push(units, dataSetInternalID=item.get("dataSetInternalID"))
        _value(unit, "name", item.get("name"))
        _value(unit, "meanValue", _number(item.get("meanValue"), 1.0))
        _lang(unit, "common:generalComment", item.get("generalComment"))


def _flow_property(root: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "flowPropertiesInformation")
    data = _data_info(information, row, direct_name=True)
    _classification(data, payload, "flowPropertiesInformation", "flow_property")
    _lang(data, "common:generalComment", row.get("description"))
    quantitative = _sub(information, "quantitativeReference")
    reference = _dig(payload, "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup")
    _reference(quantitative, "referenceToReferenceUnitGroup", reference, by_id)
    modelling = _sub(root, "modellingAndValidation")
    source = _dig(payload, "modellingAndValidation", "referenceToDataSource")
    if _ref_id(source):
        _reference(modelling, "referenceToDataSource", source, by_id)
    _placeholder_compliance(modelling)
    _admin(root, payload)


def _flow(root: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "flowInformation")
    data = _data_info(information, row)
    info = _dig(payload, "flowInformation", "dataSetInformation") or {}
    _classification(data, payload, "flowInformation", "flow")
    _value(data, "CASNumber", info.get("casNumber"))
    _value(data, "sumFormula", info.get("sumFormula"))
    _lang(data, "common:generalComment", row.get("description"))
    quantitative = _sub(information, "quantitativeReference")
    _value(
        quantitative,
        "referenceToReferenceFlowProperty",
        _dig(payload, "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty"),
    )
    modelling = _sub(root, "modellingAndValidation")
    method = _sub(modelling, "LCIMethod")
    _value(method, "typeOfDataSet", _dig(payload, "modellingAndValidation", "typeOfDataSet"))
    _placeholder_compliance(modelling)
    _admin(root, payload)
    properties = _sub(root, "flowProperties")
    for factor in _dicts(payload.get("flowProperties")):
        item = _sub(properties, "flowProperty", dataSetInternalID=factor.get("dataSetInternalID"))
        _reference(item, "referenceToFlowPropertyDataSet", factor.get("referenceToFlowPropertyDataSet"), by_id)
        _value(item, "meanValue", _number(factor.get("meanValue"), 1.0))
        _lang(item, "common:generalComment", factor.get("generalComment"))


def _source(root: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "sourceInformation")
    data = _sub(information, "dataSetInformation")
    _value(data, "common:UUID", row["id"])
    info = _dig(payload, "sourceInformation", "dataSetInformation") or {}
    _lang(data, "common:shortName", info.get("shortName") or row["name"])
    _classification(data, payload, "sourceInformation", "source")
    _value(data, "sourceCitation", info.get("sourceCitation"))
    _value(data, "publicationType", info.get("publicationType"))
    _lang(data, "sourceDescriptionOrComment", info.get("sourceDescriptionOrComment") or row.get("description"))
    if _ref_id(info.get("referenceToContact")):
        _reference(data, "referenceToContact", info.get("referenceToContact"), by_id)
    _admin(root, payload)


def _contact(root: dict[str, Any], row: dict[str, Any], _: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "contactInformation")
    data = _sub(information, "dataSetInformation")
    _value(data, "common:UUID", row["id"])
    info = _dig(payload, "contactInformation", "dataSetInformation") or {}
    _lang(data, "common:shortName", info.get("shortName") or row["name"])
    _lang(data, "common:name", info.get("name") or row["name"])
    _classification(data, payload, "contactInformation", "contact")
    for source, target in (
        ("email", "email"),
        ("wwwAddress", "WWWAddress"),
        ("contactAddress", "contactAddress"),
        ("telephone", "telephone"),
        ("telefax", "telefax"),
    ):
        _value(data, target, info.get(source))
    _lang(data, "centralContactPoint", info.get("centralContactPoint"))
    _lang(data, "contactDescriptionOrComment", info.get("generalComment") or row.get("description"))
    _admin(root, payload)


def _process(root: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "processInformation")
    data = _data_info(information, row)
    _classification(data, payload, "processInformation", "process")
    _lang(data, "common:generalComment", row.get("description"))
    quantitative = _sub(information, "quantitativeReference", type="Reference flow(s)")
    _value(
        quantitative,
        "referenceToReferenceFlow",
        _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow"),
    )
    reference_year = _dig(payload, "processInformation", "time", "referenceYear")
    time = _sub(information, "time")
    parsed_reference_year = _int(reference_year)
    _value_int(time, "common:referenceYear", parsed_reference_year if parsed_reference_year is not None else 2000)
    location = _dig(payload, "processInformation", "geography", "location")
    geography = _sub(information, "geography")
    _sub(geography, "locationOfOperationSupplyOrProduction", location=location or "GLO")
    modelling = _sub(root, "modellingAndValidation")
    method = _sub(modelling, "LCIMethodAndAllocation")
    _value(method, "typeOfDataSet", _dig(payload, "modellingAndValidation", "typeOfDataSet"))
    _placeholder_review(modelling)
    _placeholder_compliance(modelling)
    _extended_admin(root, payload)
    exchanges = _sub_array(root, "exchanges", "exchange")
    for exchange in _dicts(payload.get("exchanges")):
        item = _push(exchanges, dataSetInternalID=exchange.get("dataSetInternalID"))
        _reference(item, "referenceToFlowDataSet", exchange.get("referenceToFlowDataSet"), by_id)
        _value(item, "exchangeDirection", exchange.get("exchangeDirection"))
        _value(item, "meanAmount", _number(exchange.get("meanAmount"), 0.0))
        _value(item, "resultingAmount", _number(exchange.get("resultingAmount", exchange.get("meanAmount")), 0.0))
        _value(item, "dataDerivationTypeStatus", exchange.get("dataDerivationTypeStatus") or "Unknown derivation")
        _lang(item, "common:generalComment", exchange.get("generalComment"))


def _model(root: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> None:
    payload = row["payload"]
    information = _sub(root, "lifeCycleModelInformation")
    data = _data_info(information, row)
    _classification(data, payload, "modelInformation", "model")
    _lang(data, "common:generalComment", row.get("description"))
    quantitative = _sub(information, "quantitativeReference")
    _value_int(
        quantitative,
        "referenceToReferenceProcess",
        _int(_dig(payload, "modelInformation", "quantitativeReference", "referenceToReferenceProcess")),
    )
    technology = _sub(information, "technology")
    processes = _sub(technology, "processes")
    instances_array = _push_array(processes, "processInstance")
    outgoing: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for connection in _dicts(payload.get("connections")):
        outgoing[connection.get("fromInstanceId")].append(connection)
    instances = _dicts(payload.get("processInstances"))
    for instance in instances:
        internal_id = instance.get("dataSetInternalID")
        item = _push(
            instances_array,
            dataSetInternalID=internal_id,
            multiplicationFactor=_number(instance.get("multiplicationFactor"), 1.0),
        )
        _reference(item, "referenceToProcess", instance.get("referenceToProcess"), by_id)
        if outgoing.get(internal_id):
            connections = _sub(item, "connections")
            for connection in outgoing[internal_id]:
                flow_id = _process_reference_flow_id(instance, by_id)
                if flow_id is None:
                    raise InterchangeError(
                        "UNRESOLVED_MODEL_CONNECTION_FLOW",
                        f"Model '{row['id']}' has a connection whose upstream reference Flow cannot be resolved.",
                        details={
                            "dataset_id": row["id"],
                            "from_instance_id": internal_id,
                            "to_instance_id": connection.get("toInstanceId"),
                        },
                    )
                flow_version = _dig(by_id.get(flow_id), "payload", "administrativeInformation", "dataSetVersion") or "01.01.000"
                output = _sub(connections, "outputExchange", flowUUID=flow_id, version=flow_version)
                _sub(output, "downstreamProcess", id=connection.get("toInstanceId"), flowUUID=flow_id, version=flow_version)
    modelling = _sub(root, "modellingAndValidation")
    _placeholder_review_model(modelling)
    _placeholder_compliance(modelling)
    _extended_admin(root, payload)


def _data_info(information: dict[str, Any], row: dict[str, Any], *, direct_name: bool = False) -> dict[str, Any]:
    data = _sub(information, "dataSetInformation")
    _value(data, "common:UUID", row["id"])
    if direct_name:
        _lang(data, "common:name", row["name"])
    else:
        name = _sub(data, "name")
        _lang(name, "baseName", row["name"])
        _lang(name, "treatmentStandardsRoutes", "-")
        _lang(name, "mixAndLocationTypes", "-")
    return data


def _process_reference_flow_id(instance: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str | None:
    process_id = _ref_id(instance.get("referenceToProcess"))
    process = by_id.get(process_id) if process_id else None
    if not process:
        return None
    payload = process["payload"]
    reference_id = _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    for exchange in _dicts(payload.get("exchanges")):
        if exchange.get("dataSetInternalID") == reference_id:
            return _ref_id(exchange.get("referenceToFlowDataSet"))
    return None


_CATEGORY_ROOT = {
    # (@name, level-0 @classId, level-0 #text) confirmed valid against Tiangong's
    # real per-type category tables (tidas_*_category.json in tiangong-lca/tidas-spec).
    # Each dataset type has its OWN code table; these are not interchangeable.
    "flow": ("CPC", "0", "Agriculture, forestry and fishery products"),
    "process": ("ISIC rev.4", "A", "Agriculture, forestry and fishing"),
    "model": ("ISIC rev.4", "A", "Agriculture, forestry and fishing"),
    "unit_group": ("Technical unit groups", "1", "Technical unit groups"),
    "flow_property": ("Technical flow properties", "1", "Technical flow properties"),
    # Fetched directly from tidas_sources_category.json / tidas_contacts_category.json
    # (previously an unverified guess — these are now read from the real tables,
    # same as every other type, though never exercised by an actual Tiangong
    # validation report since no test bundle has included source/contact data).
    "source": ("Not specified", "0", "Images"),
    "contact": ("Not specified", "1", "Group of organisations, project"),
}


_CLASS_IS_ARRAY = {
    # Confirmed by fetching each type's own schema file directly:
    # tidas_processes.json / tidas_flows.json / tidas_lifecyclemodels.json
    # define common:class as an array (tuple, up to 4 levels); tidas_flowproperties.json
    # / tidas_unitgroups.json define it as a single bare object with @level
    # fixed at "0". These are NOT interchangeable — using the wrong shape is
    # what caused repeated "anyOf"/"type" failures before this fix.
    "process": True,
    "flow": True,
    "model": True,
    "unit_group": False,
    "flow_property": False,
    "source": False,
    "contact": False,
}


def _classification(data: dict[str, Any], payload: dict[str, Any], root_name: str, kind: str) -> None:
    """Fill `classificationInformation.common:classification`.

    Always uses the one confirmed-valid (classId, text) placeholder pair for
    `kind` — PRISM's own free-text `classification` values (in `payload`)
    are NOT used here, because they have no known mapping onto Tiangong's
    real per-type category tables; using them directly would very likely
    reproduce the `product_category_text_mismatch` failure this whole
    function exists to avoid. Revisit once/if a real classId<->text mapping
    is available.
    """
    information = _sub(data, "classificationInformation")
    name, class_id, text = _CATEGORY_ROOT[kind]
    if _CLASS_IS_ARRAY[kind]:
        classification = _sub(information, "common:classification")
        classification["@name"] = name
        classes = _push_array(classification, "common:class")
        item = _push(classes, level=0, classId=class_id)
        item["#text"] = text
    else:
        classification = _sub(information, "common:classification")
        item = _sub(classification, "common:class", level=0, classId=class_id)
        item["#text"] = text


def _admin(root: dict[str, Any], payload: dict[str, Any]) -> None:
    values = payload.get("administrativeInformation")
    if not isinstance(values, dict):
        values = {}
    admin = _sub(root, "administrativeInformation")
    entry = _sub(admin, "dataEntryBy")
    _value(entry, "common:timeStamp", values.get("timeStamp") or "1900-01-01T00:00:00Z")
    _reference(entry, "common:referenceToDataSetFormat", _format_reference(), {})
    publication = _sub(admin, "publicationAndOwnership")
    _value(publication, "common:dataSetVersion", values.get("dataSetVersion") or "01.01.000")
    _value(publication, "common:permanentDataSetURI", values.get("permanentDataSetURI") or _NIL_URI)
    _reference(publication, "common:referenceToOwnershipOfDataSet", _nil_contact_reference(), {})


def _extended_admin(root: dict[str, Any], payload: dict[str, Any]) -> None:
    """Same as `_admin`, plus the extra fields Tiangong's schema requires for
    Process and Model (`commissionerAndGoal`, entering-data contact, license
    fields) — mirrors `ilcd.py`'s `_extended_admin` naming for the read side.
    """
    values = payload.get("administrativeInformation")
    if not isinstance(values, dict):
        values = {}
    admin = _sub(root, "administrativeInformation")
    goal = _sub(admin, "common:commissionerAndGoal")
    commissioner = values.get("referenceToCommissioner")
    if _ref_id(commissioner):
        _reference(goal, "common:referenceToCommissioner", commissioner, {})
    else:
        _reference(goal, "common:referenceToCommissioner", _nil_contact_reference(), {})
    intended = values.get("intendedApplications")
    _lang(goal, "common:intendedApplications", intended or "Not specified")
    entry = _sub(admin, "dataEntryBy")
    _value(entry, "common:timeStamp", values.get("timeStamp") or "1900-01-01T00:00:00Z")
    _reference(entry, "common:referenceToDataSetFormat", _format_reference(), {})
    generating = values.get("referenceToPersonOrEntityGeneratingTheDataSet")
    _reference(
        entry,
        "common:referenceToPersonOrEntityEnteringTheData",
        generating if _ref_id(generating) else _nil_contact_reference(),
        {},
    )
    publication = _sub(admin, "publicationAndOwnership")
    _value(publication, "common:dataSetVersion", values.get("dataSetVersion") or "01.01.000")
    _value(publication, "common:permanentDataSetURI", values.get("permanentDataSetURI") or _NIL_URI)
    _reference(publication, "common:referenceToOwnershipOfDataSet", _nil_contact_reference(), {})
    _value(publication, "common:copyright", bool(values.get("copyright")))
    _value(publication, "common:licenseType", values.get("licenseType") or "Free of charge for all users and uses")


def _placeholder_compliance(modelling: dict[str, Any]) -> None:
    """`complianceDeclarations.compliance` requires all 7 fields below —
    confirmed by fetching `tidas_processes.json` from tiangong-lca/tidas-spec
    directly rather than guessing from error messages. `"Not defined"` is a
    valid enum member for every `*Compliance` field.
    """
    compliance = _sub(_sub(modelling, "complianceDeclarations"), "compliance")
    _reference(compliance, "common:referenceToComplianceSystem", _format_reference(), {})
    for field in (
        "common:approvalOfOverallCompliance",
        "common:nomenclatureCompliance",
        "common:methodologicalCompliance",
        "common:reviewCompliance",
        "common:documentationCompliance",
        "common:qualityCompliance",
    ):
        _value(compliance, field, "Not defined")


def _placeholder_review_model(modelling: dict[str, Any]) -> None:
    """Model's `validation.review` schema is NOT the same as Process's —
    fetched directly from `tidas_lifecyclemodels.json`: no `@type` property
    at all; `anyOf: [{required: [common:referenceToNameOfReviewerAndInstitution]}, array-of-same]`.
    """
    review = _sub(_sub(modelling, "validation"), "review")
    _reference(review, "common:referenceToNameOfReviewerAndInstitution", _nil_contact_reference(), {})


def _placeholder_review(modelling: dict[str, Any]) -> None:
    """`validation.review` requires `@type` (Process/Model only).

    `tidas_processes.json`'s schema has an `if @type == "Not reviewed" then
    {} else {require scope/reviewDetails/reviewer/report}` — using
    `"Not reviewed"` (a valid `@type` enum member) avoids the entire complex
    `common:scope`/`common:reviewDetails`/reviewer-reference/report-reference
    branch, confirmed directly from the fetched schema rather than guessed.
    """
    _sub(_sub(modelling, "validation"), "review", type="Not reviewed")


def _format_reference() -> dict[str, Any]:
    return {"type": "source", "refObjectId": _NIL_SOURCE_ID, "shortDescription": "ILCD format"}


def _nil_contact_reference() -> dict[str, Any]:
    return {"type": "contact", "refObjectId": _NIL_CONTACT_ID, "shortDescription": "Not specified"}


def _reference(
    parent: dict[str, Any],
    name: str,
    value: Any,
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target_id = _ref_id(value)
    target = by_id.get(target_id) if target_id else None
    inferred_kind = (
        target.get("type")
        if target
        else (value.get("type") if isinstance(value, dict) else None)
    )
    reference_type = {
        "model": "life cycle model data set",
        "process": "process data set",
        "flow": "flow data set",
        "flow_property": "flow property data set",
        "unit_group": "unit group data set",
        "source": "source data set",
        "contact": "contact data set",
    }.get(inferred_kind, "source data set")
    if reference_type == "life cycle model data set":
        # Confirmed by reading tidas_data_types.json's GlobalReferenceTypeValues
        # enum directly: it has no "life cycle model data set" member (the
        # enum only goes up to "LCIA method data set" / "other external
        # file"). Nothing in this codebase currently generates a reference
        # to a Model, so this has never been exercised — but silently
        # emitting an @type Tiangong's schema doesn't recognize would fail
        # validation with no clear error pointing back here. Fail loudly
        # instead if/when something starts referencing a Model.
        raise InterchangeError(
            "UNSUPPORTED_TIDAS_REFERENCE_TYPE",
            "TIDAS JSON export cannot reference a Model — Tiangong's "
            "GlobalReferenceTypeValues enum has no 'life cycle model data "
            "set' member.",
            details={"target_id": target_id},
        )
    folder = {
        "life cycle model data set": "lifecyclemodels",
        "process data set": "processes",
        "flow data set": "flows",
        "flow property data set": "flowproperties",
        "unit group data set": "unitgroups",
        "source data set": "sources",
        "contact data set": "contacts",
    }[reference_type]
    version = _dig(target, "payload", "administrativeInformation", "dataSetVersion") if target else None
    version = version or "01.01.000"
    element = _sub(
        parent,
        name,
        type=reference_type,
        refObjectId=target_id,
        version=version,
        uri=f"../{folder}/{target_id}.json" if target_id else None,
    )
    description = target.get("name") if target else None
    if not description and isinstance(value, dict):
        description = value.get("shortDescription")
    if description:
        _lang(element, "common:shortDescription", description)
    return element


def _lang(parent: dict[str, Any], name: str, value: Any) -> None:
    for item in _language_values(value):
        node = _sub(parent, name, **{"xml:lang": item["lang"]})
        node["#text"] = item["text"]


def _language_values(value: Any) -> list[dict[str, str]]:
    if isinstance(value, str):
        return [{"lang": "en", "text": value}] if value else []
    if not isinstance(value, list):
        return []
    return [
        {"lang": str(item.get("lang") or "en"), "text": item["text"]}
        for item in value
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]
    ]


def _new_node(**attributes: Any) -> dict[str, Any]:
    return {f"@{key}": _string(value) for key, value in attributes.items() if value is not None}


def _add_child(parent: dict[str, Any], name: str, child: Any) -> None:
    """Attach `child` under `name`; a second occurrence upgrades the slot to a list."""
    if name in parent:
        existing = parent[name]
        if isinstance(existing, list):
            existing.append(child)
        else:
            parent[name] = [existing, child]
    else:
        parent[name] = child


def _sub(parent: dict[str, Any], name: str, **attributes: Any) -> dict[str, Any]:
    node = _new_node(**attributes)
    _add_child(parent, name, node)
    return node


def _sub_array(parent: dict[str, Any], container_name: str, item_name: str) -> list[Any]:
    """Create `parent[container_name][item_name]` as a JSON array, even when
    it ends up with zero or one items — Tiangong's schema requires an array
    here (confirmed: `exchanges.exchange` failed with "not of type array"
    when a single exchange was emitted as a bare object).
    """
    container = _sub(parent, container_name)
    return _push_array(container, item_name)


def _push_array(container: dict[str, Any], item_name: str) -> list[Any]:
    items: list[Any] = []
    container[item_name] = items
    return items


def _push(array: list[Any], **attributes: Any) -> dict[str, Any]:
    node = _new_node(**attributes)
    array.append(node)
    return node


def _value(parent: dict[str, Any], name: str, value: Any) -> None:
    """Emit `value` as element text — always a JSON string.

    Real Tiangong validation reports show internal-ID-reference and amount
    fields (`referenceToReferenceFlow`, `meanAmount`, `resultingAmount`,
    `referenceToReferenceUnit`, ...) are typed as JSON string in the schema
    (`$defs/Real`, `$defs/Int5`, `$defs/Int6` all rejected a JSON number),
    even though a real Tiangong *export* emits some of these as bare numbers.
    `referenceToReferenceProcess` (Model) is the one confirmed exception —
    see `_value_int`.
    """
    if value is None or value == "":
        return
    _add_child(parent, name, _string(value))


def _value_int(parent: dict[str, Any], name: str, value: Any) -> None:
    """Emit `value` as a JSON integer — confirmed required for
    `referenceToReferenceProcess` (Model quantitativeReference) specifically;
    do not reuse this for other internal-reference fields without a report
    confirming they need it too (most need `_value`/string instead).
    """
    if value is None:
        return
    _add_child(parent, name, value)


def _string(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return default


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ref_id(value: Any) -> str | None:
    result = value.get("refObjectId") if isinstance(value, dict) else None
    return result if isinstance(result, str) and result else None


def _dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
