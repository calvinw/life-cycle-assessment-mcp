"""PRISM workspace bundle to deterministic ILCD/eILCD XML ZIP export."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any
from xml.etree import ElementTree as ET

from .archive import write_deterministic_zip
from .bundle import PLURAL_KEYS, prepare_export_bundle
from .errors import InterchangeError
from .ilcd import DATASET_FOLDERS, ROOT_NAMESPACES

COMMON_NS = "http://lca.jrc.it/ILCD/Common"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

for _prefix, _namespace in {
    "common": COMMON_NS,
    "model": ROOT_NAMESPACES["model"],
    "p": ROOT_NAMESPACES["process"],
    "f": ROOT_NAMESPACES["flow"],
    "fp": ROOT_NAMESPACES["flow_property"],
    "u": ROOT_NAMESPACES["unit_group"],
    "s": ROOT_NAMESPACES["source"],
    "c": ROOT_NAMESPACES["contact"],
}.items():
    ET.register_namespace(_prefix, _namespace)


def export_ilcd(bundle: dict[str, Any], model_id: str | None = None) -> bytes:
    """Convert a PRISM bundle into a self-contained ILCD/eILCD ZIP."""
    prepared = prepare_export_bundle(bundle, model_id)
    records = [row for plural in PLURAL_KEYS.values() for row in prepared[plural]]
    by_id = {row["id"]: row for row in records}
    entries: dict[str, bytes] = {}
    for row in sorted(records, key=lambda item: (item["type"], item["id"])):
        root = _serialize(row, by_id)
        folder = DATASET_FOLDERS[row["type"]][0]
        entries[f"ILCD/{folder}/{row['id']}.xml"] = ET.tostring(
            root, encoding="utf-8", xml_declaration=True, short_empty_elements=True
        )
    return write_deterministic_zip(entries)


def _serialize(
    row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> ET.Element:
    kind = row["type"]
    namespace = ROOT_NAMESPACES[kind]
    attributes = {"version": "1.1"}
    if kind == "model":
        attributes["locations"] = "../ILCDLocations.xml"
    root = ET.Element(_q(namespace, DATASET_FOLDERS[kind][1]), attributes)
    {
        "unit_group": _unit_group,
        "flow_property": _flow_property,
        "flow": _flow,
        "source": _source,
        "contact": _contact,
        "process": _process,
        "model": _model,
    }[kind](root, namespace, row, by_id)
    return root


def _unit_group(
    root: ET.Element, ns: str, row: dict[str, Any], _: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "unitGroupInformation")
    data = _data_info(information, ns, row, direct_name=True)
    _classification(data, ns, payload, "unitGroupInformation")
    _comments(data, COMMON_NS, "generalComment", row.get("description"))
    quantitative = _sub(information, ns, "quantitativeReference")
    _value(
        quantitative,
        ns,
        "referenceToReferenceUnit",
        _dig(payload, "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit"),
    )
    _admin(root, ns, payload)
    units = _sub(root, ns, "units")
    for item in _dicts(payload.get("units")):
        unit = _sub(units, ns, "unit", dataSetInternalID=item.get("dataSetInternalID"))
        _value(unit, ns, "name", item.get("name"))
        _value(unit, ns, "meanValue", _number(item.get("meanValue"), 1.0))
        _comments(unit, COMMON_NS, "generalComment", item.get("generalComment"))


def _flow_property(
    root: ET.Element, ns: str, row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "flowPropertiesInformation")
    data = _data_info(information, ns, row, direct_name=True)
    _classification(data, ns, payload, "flowPropertiesInformation")
    _comments(data, COMMON_NS, "generalComment", row.get("description"))
    quantitative = _sub(information, ns, "quantitativeReference")
    reference = _dig(
        payload,
        "flowPropertiesInformation",
        "quantitativeReference",
        "referenceToReferenceUnitGroup",
    )
    _reference(quantitative, ns, "referenceToReferenceUnitGroup", reference, by_id)
    modelling = _sub(root, ns, "modellingAndValidation")
    source = _dig(payload, "modellingAndValidation", "referenceToDataSource")
    if _ref_id(source):
        _reference(modelling, ns, "referenceToDataSource", source, by_id)
    _admin(root, ns, payload)


def _flow(
    root: ET.Element, ns: str, row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "flowInformation")
    data = _data_info(information, ns, row)
    info = _dig(payload, "flowInformation", "dataSetInformation") or {}
    _classification(data, ns, payload, "flowInformation")
    _value(data, ns, "CASNumber", info.get("casNumber"))
    _value(data, ns, "sumFormula", info.get("sumFormula"))
    _comments(data, COMMON_NS, "generalComment", row.get("description"))
    quantitative = _sub(information, ns, "quantitativeReference")
    _value(
        quantitative,
        ns,
        "referenceToReferenceFlowProperty",
        _dig(payload, "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty"),
    )
    modelling = _sub(root, ns, "modellingAndValidation")
    method = _sub(modelling, ns, "LCIMethod")
    _value(method, ns, "typeOfDataSet", _dig(payload, "modellingAndValidation", "typeOfDataSet"))
    _admin(root, ns, payload)
    properties = _sub(root, ns, "flowProperties")
    for factor in _dicts(payload.get("flowProperties")):
        item = _sub(properties, ns, "flowProperty", dataSetInternalID=factor.get("dataSetInternalID"))
        _reference(item, ns, "referenceToFlowPropertyDataSet", factor.get("referenceToFlowPropertyDataSet"), by_id)
        _value(item, ns, "meanValue", _number(factor.get("meanValue"), 1.0))
        _comments(item, COMMON_NS, "generalComment", factor.get("generalComment"))


def _source(
    root: ET.Element, ns: str, row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "sourceInformation")
    data = _sub(information, ns, "dataSetInformation")
    _value(data, COMMON_NS, "UUID", row["id"])
    info = _dig(payload, "sourceInformation", "dataSetInformation") or {}
    _lang(data, COMMON_NS, "shortName", info.get("shortName") or row["name"])
    _classification(data, ns, payload, "sourceInformation")
    _value(data, ns, "sourceCitation", info.get("sourceCitation"))
    _value(data, ns, "publicationType", info.get("publicationType"))
    _comments(data, ns, "sourceDescriptionOrComment", info.get("sourceDescriptionOrComment") or row.get("description"))
    if _ref_id(info.get("referenceToContact")):
        _reference(data, ns, "referenceToContact", info.get("referenceToContact"), by_id)
    _admin(root, ns, payload)


def _contact(
    root: ET.Element, ns: str, row: dict[str, Any], _: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "contactInformation")
    data = _sub(information, ns, "dataSetInformation")
    _value(data, COMMON_NS, "UUID", row["id"])
    info = _dig(payload, "contactInformation", "dataSetInformation") or {}
    _lang(data, COMMON_NS, "shortName", info.get("shortName") or row["name"])
    _lang(data, COMMON_NS, "name", info.get("name") or row["name"])
    _classification(data, ns, payload, "contactInformation")
    for source, target in (
        ("email", "email"),
        ("wwwAddress", "WWWAddress"),
        ("contactAddress", "contactAddress"),
        ("telephone", "telephone"),
        ("telefax", "telefax"),
    ):
        _value(data, ns, target, info.get(source))
    _comments(data, ns, "centralContactPoint", info.get("centralContactPoint"))
    _comments(
        data,
        ns,
        "contactDescriptionOrComment",
        info.get("generalComment") or row.get("description"),
    )
    _admin(root, ns, payload)


def _process(
    root: ET.Element, ns: str, row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "processInformation")
    data = _data_info(information, ns, row)
    _classification(data, ns, payload, "processInformation")
    _comments(data, COMMON_NS, "generalComment", row.get("description"))
    quantitative = _sub(information, ns, "quantitativeReference")
    _value(
        quantitative,
        ns,
        "referenceToReferenceFlow",
        _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow"),
    )
    reference_year = _dig(payload, "processInformation", "time", "referenceYear")
    if reference_year is not None:
        time = _sub(information, ns, "time")
        _value(time, ns, "referenceYear", reference_year)
    location = _dig(payload, "processInformation", "geography", "location")
    if location:
        geography = _sub(information, ns, "geography")
        _sub(geography, ns, "locationOfOperationSupplyOrProduction", location=location)
    modelling = _sub(root, ns, "modellingAndValidation")
    method = _sub(modelling, ns, "LCIMethodAndAllocation")
    _value(method, ns, "typeOfDataSet", _dig(payload, "modellingAndValidation", "typeOfDataSet"))
    _admin(root, ns, payload)
    exchanges = _sub(root, ns, "exchanges")
    for exchange in _dicts(payload.get("exchanges")):
        item = _sub(exchanges, ns, "exchange", dataSetInternalID=exchange.get("dataSetInternalID"))
        _reference(item, ns, "referenceToFlowDataSet", exchange.get("referenceToFlowDataSet"), by_id)
        _value(item, ns, "exchangeDirection", exchange.get("exchangeDirection"))
        _value(item, ns, "meanAmount", _number(exchange.get("meanAmount"), 0.0))
        _value(item, ns, "resultingAmount", _number(exchange.get("resultingAmount", exchange.get("meanAmount")), 0.0))
        _comments(item, COMMON_NS, "generalComment", exchange.get("generalComment"))


def _model(
    root: ET.Element, ns: str, row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    information = _sub(root, ns, "lifeCycleModelInformation")
    data = _data_info(information, ns, row)
    _classification(data, ns, payload, "modelInformation")
    _comments(data, COMMON_NS, "generalComment", row.get("description"))
    quantitative = _sub(information, ns, "quantitativeReference")
    _value(
        quantitative,
        ns,
        "referenceToReferenceProcess",
        _dig(payload, "modelInformation", "quantitativeReference", "referenceToReferenceProcess"),
    )
    technology = _sub(information, ns, "technology")
    processes = _sub(technology, ns, "processes")
    outgoing: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for connection in _dicts(payload.get("connections")):
        outgoing[connection.get("fromInstanceId")].append(connection)
    instances = _dicts(payload.get("processInstances"))
    for instance in instances:
        internal_id = instance.get("dataSetInternalID")
        item = _sub(
            processes,
            ns,
            "processInstance",
            dataSetInternalID=internal_id,
            multiplicationFactor=_number(instance.get("multiplicationFactor"), 1.0),
        )
        _reference(item, ns, "referenceToProcess", instance.get("referenceToProcess"), by_id)
        if outgoing.get(internal_id):
            connections = _sub(item, ns, "connections")
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
                output = _sub(connections, ns, "outputExchange", flowUUID=flow_id)
                _sub(
                    output,
                    ns,
                    "downstreamProcess",
                    id=connection.get("toInstanceId"),
                    flowUUID=flow_id,
                )
    _sub(root, ns, "modellingAndValidation")
    _admin(root, ns, payload)


def _data_info(
    information: ET.Element, ns: str, row: dict[str, Any], *, direct_name: bool = False
) -> ET.Element:
    data = _sub(information, ns, "dataSetInformation")
    _value(data, COMMON_NS, "UUID", row["id"])
    if direct_name:
        _lang(data, COMMON_NS, "name", row["name"])
    else:
        name = _sub(data, ns, "name")
        _lang(name, ns, "baseName", row["name"])
    return data


def _process_reference_flow_id(
    instance: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> str | None:
    process_id = _ref_id(instance.get("referenceToProcess"))
    process = by_id.get(process_id) if process_id else None
    if not process:
        return None
    payload = process["payload"]
    reference_id = _dig(
        payload,
        "processInformation",
        "quantitativeReference",
        "referenceToReferenceFlow",
    )
    for exchange in _dicts(payload.get("exchanges")):
        if exchange.get("dataSetInternalID") == reference_id:
            return _ref_id(exchange.get("referenceToFlowDataSet"))
    return None


def _classification(data: ET.Element, ns: str, payload: dict[str, Any], root_name: str) -> None:
    values = _dig(payload, root_name, "dataSetInformation", "classification")
    if not isinstance(values, list) or not values:
        return
    information = _sub(data, ns, "classificationInformation")
    classification = _sub(information, COMMON_NS, "classification")
    for level, value in enumerate(values):
        if str(value):
            item = _sub(classification, COMMON_NS, "class", level=level)
            item.text = str(value)


def _admin(root: ET.Element, ns: str, payload: dict[str, Any]) -> None:
    values = payload.get("administrativeInformation")
    if not isinstance(values, dict):
        values = {}
    admin = _sub(root, ns, "administrativeInformation")
    entry = _sub(admin, ns, "dataEntryBy")
    _value(entry, COMMON_NS, "timeStamp", values.get("timeStamp"))
    publication = _sub(admin, ns, "publicationAndOwnership")
    _value(publication, COMMON_NS, "dataSetVersion", values.get("dataSetVersion") or "01.01.000")
    _value(publication, COMMON_NS, "permanentDataSetURI", values.get("permanentDataSetURI"))


def _reference(
    parent: ET.Element,
    ns: str,
    name: str,
    value: Any,
    by_id: dict[str, dict[str, Any]],
) -> ET.Element:
    target_id = _ref_id(value)
    target = by_id.get(target_id) if target_id else None
    reference_type = {
        "model": "life cycle model data set",
        "process": "process data set",
        "flow": "flow data set",
        "flow_property": "flow property data set",
        "unit_group": "unit group data set",
        "source": "source data set",
        "contact": "contact data set",
    }.get(target.get("type") if target else None)
    version = _dig(target, "payload", "administrativeInformation", "dataSetVersion") if target else None
    element = _sub(
        parent,
        ns,
        name,
        type=reference_type,
        refObjectId=target_id,
        version=version or "01.01.000",
    )
    description = target.get("name") if target else None
    if not description and isinstance(value, dict):
        description = value.get("shortDescription")
    if description:
        _lang(element, COMMON_NS, "shortDescription", description)
    return element


def _comments(parent: ET.Element, ns: str, name: str, value: Any) -> None:
    for item in _language_values(value):
        element = _sub(parent, ns, name)
        element.set(XML_LANG, item["lang"])
        element.text = item["text"]


def _lang(parent: ET.Element, ns: str, name: str, value: Any) -> None:
    items = _language_values(value)
    if not items:
        return
    for item in items:
        element = _sub(parent, ns, name)
        element.set(XML_LANG, item["lang"])
        element.text = item["text"]


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


def _sub(parent: ET.Element, ns: str, name: str, **attributes: Any) -> ET.Element:
    clean = {key: _string(value) for key, value in attributes.items() if value is not None}
    return ET.SubElement(parent, _q(ns, name), clean)


def _value(parent: ET.Element, ns: str, name: str, value: Any) -> ET.Element | None:
    if value is None or value == "":
        return None
    element = _sub(parent, ns, name)
    element.text = _string(value)
    return element


def _q(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


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
