"""ILCD/eILCD XML ZIP to PRISM workspace conversion."""

from __future__ import annotations

import re
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from .archive import open_safe_zip
from .errors import InterchangeError

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

DATASET_FOLDERS = {
    "model": ("lifecyclemodels", "lifeCycleModelDataSet"),
    "process": ("processes", "processDataSet"),
    "flow": ("flows", "flowDataSet"),
    "flow_property": ("flowproperties", "flowPropertyDataSet"),
    "unit_group": ("unitgroups", "unitGroupDataSet"),
    "source": ("sources", "sourceDataSet"),
    "contact": ("contacts", "contactDataSet"),
}
FOLDER_DATASETS = {folder: kind for kind, (folder, _) in DATASET_FOLDERS.items()}
ROOT_NAMESPACES = {
    "model": "http://eplca.jrc.ec.europa.eu/ILCD/LifeCycleModel/2017",
    "process": "http://lca.jrc.it/ILCD/Process",
    "flow": "http://lca.jrc.it/ILCD/Flow",
    "flow_property": "http://lca.jrc.it/ILCD/FlowProperty",
    "unit_group": "http://lca.jrc.it/ILCD/UnitGroup",
    "source": "http://lca.jrc.it/ILCD/Source",
    "contact": "http://lca.jrc.it/ILCD/Contact",
}
_KNOWN_NAMESPACES = {
    "",
    "http://lca.jrc.it/ILCD/Common",
    *ROOT_NAMESPACES.values(),
}
_OPENLCA_JSON_FOLDERS = {
    "actors",
    "flows",
    "flow_properties",
    "processes",
    "product_systems",
    "sources",
    "unit_groups",
}


def preview_ilcd(package: bytes) -> dict[str, Any]:
    """Read an ILCD/eILCD package and return normalized PRISM preview rows."""
    archive = open_safe_zip(package)
    warnings: list[dict[str, Any]] = []
    parsed: list[tuple[str, ET.Element, str]] = []
    with archive:
        names = {info.filename for info in archive.infolist()}
        if not any(name.startswith("ILCD/") for name in names):
            raise InterchangeError(
                "MISSING_ILCD_DIRECTORY",
                "The ZIP does not contain a top-level ILCD directory.",
                status_code=400,
            )
        if any(
            name.endswith(".json")
            and name.split("/", 1)[0] in _OPENLCA_JSON_FOLDERS
            for name in names
        ):
            warnings.append(
                _warning(
                    "HYBRID_ILCD_OPENLCA_PACKAGE",
                    "The package contains both ILCD XML and openLCA JSON; imported its ILCD representation.",
                )
            )
        for info in archive.infolist():
            if info.is_dir() or not info.filename.endswith(".xml"):
                continue
            parts = info.filename.split("/")
            if len(parts) != 3 or parts[0] != "ILCD":
                warnings.append(_warning("UNSUPPORTED_PACKAGE_ENTRY", f"Ignored '{info.filename}'.", path=info.filename))
                continue
            kind = FOLDER_DATASETS.get(parts[1])
            if kind is None:
                warnings.append(_warning("UNSUPPORTED_PACKAGE_ENTRY", f"Ignored '{info.filename}'.", path=info.filename))
                continue
            root = _read_xml_member(archive, info.filename)
            expected_root = DATASET_FOLDERS[kind][1]
            root_namespace = _namespace(root.tag)
            if _local(root.tag) != expected_root or root_namespace not in {
                "",
                ROOT_NAMESPACES[kind],
            }:
                raise InterchangeError(
                    "ILCD_TYPE_MISMATCH",
                    f"'{info.filename}' does not contain a {expected_root}.",
                    details={
                        "path": info.filename,
                        "actual_type": _local(root.tag),
                        "actual_namespace": root_namespace,
                    },
                )
            parsed.append((kind, root, info.filename))

    if not parsed:
        raise InterchangeError("EMPTY_ILCD_PACKAGE", "The package contains no supported datasets.")

    rows: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for kind, root, path in parsed:
        source_id = _required_uuid(root, path)
        if source_id in source_ids:
            raise InterchangeError(
                "DUPLICATE_ILCD_ID",
                f"The package contains duplicate dataset id '{source_id}'.",
                details={"dataset_id": source_id},
            )
        source_ids.add(source_id)
        if path.rsplit("/", 1)[-1] != f"{source_id}.xml":
            warnings.append(
                _warning(
                    "ILCD_FILENAME_ID_MISMATCH",
                    f"The filename for '{source_id}' does not match its UUID.",
                    path=path,
                )
            )
        rows.append(_convert(root, kind, source_id))

    _validate_references(rows, warnings)
    rows.sort(key=lambda row: (row["type"], row["name"].casefold(), row["id"]))
    summary = {kind: 0 for kind in DATASET_FOLDERS}
    for row in rows:
        summary[row["type"]] += 1
    return {
        "format": "ilcd-xml",
        "valid": True,
        "summary": summary,
        "datasets": rows,
        "matches": [],
        "warnings": warnings,
        "errors": [],
    }


def _read_xml_member(archive: zipfile.ZipFile, path: str) -> ET.Element:
    try:
        raw = archive.read(path)
        upper = raw.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise ValueError("DTD and entity declarations are not allowed")
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError, UnicodeError, ValueError) as exc:
        raise InterchangeError(
            "INVALID_ILCD_XML",
            f"'{path}' is not safe, well-formed ILCD XML.",
            details={"path": path},
            status_code=400,
        ) from exc


def _required_uuid(root: ET.Element, path: str) -> str:
    element = _first_descendant(root, "UUID")
    value = _text(element)
    if not value:
        raise InterchangeError(
            "MISSING_ILCD_UUID",
            f"'{path}' has no UUID.",
            details={"path": path},
        )
    if not _UUID_RE.match(value):
        raise InterchangeError(
            "INVALID_ILCD_UUID",
            f"'{path}' has an invalid UUID.",
            details={"path": path, "uuid": value},
        )
    return value


def _convert(root: ET.Element, kind: str, source_id: str) -> dict[str, Any]:
    info_root = {
        "model": "lifeCycleModelInformation",
        "process": "processInformation",
        "flow": "flowInformation",
        "flow_property": "flowPropertiesInformation",
        "unit_group": "unitGroupInformation",
        "source": "sourceInformation",
        "contact": "contactInformation",
    }[kind]
    information = _child(root, info_root)
    data_info = _child(information, "dataSetInformation")
    name = _dataset_name(data_info, source_id)
    description_field = (
        "sourceDescriptionOrComment" if kind == "source" else "generalComment"
    )
    description = _join_texts(_lang_elements(data_info, description_field))
    payload = _payload(root, kind, information, data_info)
    return {
        "temporary_id": f"import:{kind}:{source_id}",
        "source_id": source_id,
        "id": source_id,
        "type": kind,
        "name": name,
        "description": description,
        "payload": payload,
        "decision": "create",
    }


def _payload(
    root: ET.Element,
    kind: str,
    information: ET.Element | None,
    data_info: ET.Element | None,
) -> dict[str, Any]:
    classification = _classification(data_info)
    general_comment = _lang_elements(data_info, "generalComment")
    admin = _administrative_information(root)

    if kind == "unit_group":
        quantitative = _child(information, "quantitativeReference")
        units_parent = _child(root, "units")
        return {
            "unitGroupInformation": {
                "dataSetInformation": {
                    "name": _name_lang(data_info),
                    "classification": classification,
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceUnit": _integer(_text(_child(quantitative, "referenceToReferenceUnit")))
                },
            },
            "modellingAndValidation": {"complianceDeclarations": []},
            "administrativeInformation": admin,
            "units": [
                {
                    "dataSetInternalID": _integer(unit.get("dataSetInternalID")),
                    "name": _text(_child(unit, "name")),
                    "meanValue": _float(_text(_child(unit, "meanValue")), 1.0),
                    "generalComment": _lang_elements(unit, "generalComment"),
                }
                for unit in _children(units_parent, "unit")
            ],
        }

    if kind == "flow_property":
        quantitative = _child(information, "quantitativeReference")
        return {
            "flowPropertiesInformation": {
                "dataSetInformation": {
                    "name": _name_lang(data_info),
                    "classification": classification,
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceUnitGroup": _reference(
                        _child(quantitative, "referenceToReferenceUnitGroup"), "unit_group"
                    )
                },
            },
            "modellingAndValidation": {
                "referenceToDataSource": _reference(
                    _first_descendant(root, "referenceToDataSource"), "source"
                ),
                "complianceDeclarations": [],
            },
            "administrativeInformation": admin,
        }

    if kind == "flow":
        quantitative = _child(information, "quantitativeReference")
        modelling = _child(root, "modellingAndValidation")
        method = _child(modelling, "LCIMethod")
        properties = _child(root, "flowProperties")
        return {
            "flowInformation": {
                "dataSetInformation": {
                    "name": {"baseName": _name_lang(data_info), "treatmentStandardsRoutes": [], "mixAndLocationTypes": []},
                    "classification": classification,
                    "casNumber": _text(_child(data_info, "CASNumber")),
                    "sumFormula": _text(_child(data_info, "sumFormula")),
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceFlowProperty": _integer(_text(_child(quantitative, "referenceToReferenceFlowProperty")))
                },
            },
            "modellingAndValidation": {
                "typeOfDataSet": _text(_child(method, "typeOfDataSet")),
                "complianceDeclarations": [],
            },
            "administrativeInformation": admin,
            "flowProperties": [
                {
                    "dataSetInternalID": _integer(item.get("dataSetInternalID")),
                    "referenceToFlowPropertyDataSet": _reference(_child(item, "referenceToFlowPropertyDataSet"), "flow_property"),
                    "meanValue": _float(_text(_child(item, "meanValue")), 1.0),
                    "generalComment": _lang_elements(item, "generalComment"),
                }
                for item in _children(properties, "flowProperty")
            ],
        }

    if kind == "process":
        quantitative = _child(information, "quantitativeReference")
        geography = _child(information, "geography")
        location = _child(geography, "locationOfOperationSupplyOrProduction")
        modelling = _child(root, "modellingAndValidation")
        method = _child(modelling, "LCIMethodAndAllocation")
        exchanges = _child(root, "exchanges")
        return {
            "processInformation": {
                "dataSetInformation": {
                    "name": {"baseName": _name_lang(data_info), "treatmentStandardsRoutes": [], "mixAndLocationTypes": []},
                    "classification": classification,
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceFlow": _integer(_text(_child(quantitative, "referenceToReferenceFlow")))
                },
                "time": {"referenceYear": _integer(_text(_first_descendant(_child(information, "time"), "referenceYear")))},
                "geography": {"location": location.get("location", "") if location is not None else ""},
            },
            "modellingAndValidation": {
                "typeOfDataSet": _text(_child(method, "typeOfDataSet")),
                "dataCutOffAndCompletenessPrinciples": [],
                "referenceToDataSource": _empty_ref("source"),
                "annualSupplyOrProductionVolume": [],
                "complianceDeclarations": [],
            },
            "administrativeInformation": _extended_admin(root, admin),
            "exchanges": [
                {
                    "dataSetInternalID": _integer(item.get("dataSetInternalID")),
                    "referenceToFlowDataSet": _reference(_child(item, "referenceToFlowDataSet"), "flow"),
                    "exchangeDirection": _text(_child(item, "exchangeDirection")),
                    "meanAmount": _float(_text(_child(item, "meanAmount")), _float(item.get("amount"), 0.0)),
                    "resultingAmount": _float(_text(_child(item, "resultingAmount")), _float(item.get("amount"), 0.0)),
                    "generalComment": _lang_elements(item, "generalComment"),
                }
                for item in _children(exchanges, "exchange")
            ],
        }

    if kind == "model":
        quantitative = _child(information, "quantitativeReference")
        processes = _path(information, "technology", "processes")
        instances = _children(processes, "processInstance")
        connections = []
        for instance in instances:
            upstream = _integer(instance.get("dataSetInternalID"))
            for downstream in _descendants(instance, "downstreamProcess"):
                connections.append(
                    {"fromInstanceId": upstream, "toInstanceId": _integer(downstream.get("id"))}
                )
        return {
            "modelInformation": {
                "dataSetInformation": {
                    "name": {"baseName": _name_lang(data_info), "treatmentStandardsRoutes": [], "mixAndLocationTypes": []},
                    "classification": classification,
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceProcess": _integer(_text(_child(quantitative, "referenceToReferenceProcess")))
                },
            },
            "modellingAndValidation": {"complianceDeclarations": []},
            "administrativeInformation": _extended_admin(root, admin),
            "processInstances": [
                {
                    "dataSetInternalID": _integer(item.get("dataSetInternalID")),
                    "referenceToProcess": _reference(_child(item, "referenceToProcess"), "process"),
                    "multiplicationFactor": _float(item.get("multiplicationFactor"), 1.0),
                }
                for item in instances
            ],
            "connections": connections,
        }

    if kind == "source":
        source_comment = _lang_elements(data_info, "sourceDescriptionOrComment")
        return {
            "sourceInformation": {"dataSetInformation": {
                "shortName": _field_lang(data_info, "shortName"), "classification": classification,
                "sourceCitation": _text(_child(data_info, "sourceCitation")),
                "publicationType": _text(_child(data_info, "publicationType")),
                "sourceDescriptionOrComment": source_comment,
                "referenceToContact": _reference(_child(data_info, "referenceToContact"), "contact"),
            }},
            "administrativeInformation": admin,
        }

    if kind == "contact":
        short_name = _field_lang(data_info, "shortName")
        full_name = _field_lang(data_info, "name")
        return {
            "contactInformation": {"dataSetInformation": {
                "shortName": short_name, "name": full_name or short_name,
                "classification": classification,
                "email": _text(_child(data_info, "email")),
                "wwwAddress": _text(_child(data_info, "WWWAddress")),
                "centralContactPoint": _lang_elements(data_info, "centralContactPoint"),
                "contactAddress": _text(_child(data_info, "contactAddress")),
                "telephone": _text(_child(data_info, "telephone")),
                "telefax": _text(_child(data_info, "telefax")),
                "generalComment": general_comment,
                "referenceToContact": [],
            }},
            "administrativeInformation": admin,
        }
    raise AssertionError(kind)


def _validate_references(rows: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    available = {row["id"]: row["type"] for row in rows}
    for row in rows:
        payload = row["payload"]
        if row["type"] == "model":
            instances = payload["processInstances"]
            instance_ids = [item["dataSetInternalID"] for item in instances]
            if any(value is None for value in instance_ids) or len(instance_ids) != len(
                set(instance_ids)
            ):
                raise InterchangeError(
                    "INVALID_ILCD_PROCESS_INSTANCE_ID",
                    f"Model '{row['name']}' has missing or duplicate process instance IDs.",
                    details={"dataset_id": row["id"], "instance_ids": instance_ids},
                )
            internal_ids = set(instance_ids)
            reference_id = payload["modelInformation"]["quantitativeReference"]["referenceToReferenceProcess"]
            if reference_id not in internal_ids:
                raise InterchangeError(
                    "UNRESOLVED_DATASET_REFERENCE",
                    f"Model '{row['name']}' has no resolvable reference process instance.",
                    details={"dataset_id": row["id"], "instance_id": reference_id},
                )
            for item in instances:
                target = item["referenceToProcess"].get("refObjectId")
                if not target or available.get(target) != "process":
                    raise InterchangeError(
                        "UNRESOLVED_DATASET_REFERENCE",
                        f"Model '{row['name']}' references a Process outside this package.",
                        details={"dataset_id": row["id"], "reference_id": target},
                    )
            for connection in payload["connections"]:
                if connection["fromInstanceId"] not in internal_ids or connection["toInstanceId"] not in internal_ids:
                    raise InterchangeError(
                        "UNRESOLVED_DATASET_REFERENCE",
                        f"Model '{row['name']}' contains a connection to an unknown process instance.",
                        details={"dataset_id": row["id"], **connection},
                    )
        elif row["type"] == "process":
            for index, exchange in enumerate(payload["exchanges"]):
                _warn_missing(row, exchange["referenceToFlowDataSet"], "flow", available, warnings, f"exchanges[{index}].referenceToFlowDataSet")
        elif row["type"] == "flow":
            properties = payload["flowProperties"]
            reference_id = payload["flowInformation"]["quantitativeReference"]["referenceToReferenceFlowProperty"]
            if reference_id is not None and reference_id not in {item["dataSetInternalID"] for item in properties}:
                warnings.append(_warning("UNRESOLVED_DATASET_REFERENCE", f"Flow '{row['name']}' has no resolvable reference Flow Property.", dataset_id=row["id"], internal_id=reference_id))
            for index, item in enumerate(properties):
                _warn_missing(row, item["referenceToFlowPropertyDataSet"], "flow_property", available, warnings, f"flowProperties[{index}].referenceToFlowPropertyDataSet")
        elif row["type"] == "flow_property":
            reference = payload["flowPropertiesInformation"]["quantitativeReference"]["referenceToReferenceUnitGroup"]
            _warn_missing(row, reference, "unit_group", available, warnings, "flowPropertiesInformation.quantitativeReference.referenceToReferenceUnitGroup")
        elif row["type"] == "source":
            reference = payload["sourceInformation"]["dataSetInformation"]["referenceToContact"]
            _warn_missing(row, reference, "contact", available, warnings, "sourceInformation.dataSetInformation.referenceToContact")


def _warn_missing(row: dict[str, Any], reference: dict[str, Any], expected_type: str, available: dict[str, str], warnings: list[dict[str, Any]], path: str) -> None:
    target = reference.get("refObjectId")
    if target and available.get(target) != expected_type:
        warnings.append(_warning("UNRESOLVED_DATASET_REFERENCE", f"'{row['name']}' references a dataset outside this package.", dataset_id=row["id"], reference_id=target, path=path))


def _administrative_information(root: ET.Element) -> dict[str, Any]:
    ownership = _first_descendant(root, "referenceToOwnershipOfDataSet")
    return {
        "referenceToOwnershipOfDataSet": _reference(ownership, "contact"),
        "dataSetVersion": _text(_first_descendant(root, "dataSetVersion")) or "01.01.000",
        "permanentDataSetURI": _text(_first_descendant(root, "permanentDataSetURI")),
        "timeStamp": _text(_first_descendant(root, "timeStamp")),
    }


def _extended_admin(
    root: ET.Element, admin: dict[str, Any]
) -> dict[str, Any]:
    goal = _first_descendant(root, "commissionerAndGoal")
    return {
        **admin,
        "referenceToCommissioner": _reference(
            _first_descendant(goal, "referenceToCommissioner"), "contact"
        ),
        "intendedApplications": _lang_elements(goal, "intendedApplications"),
        "referenceToPersonOrEntityGeneratingTheDataSet": _reference(
            _first_descendant(
                root, "referenceToPersonOrEntityGeneratingTheDataSet"
            ),
            "contact",
        ),
        "copyright": _boolean(
            _text(_first_descendant(root, "copyright")), False
        ),
        "licenseType": _text(_first_descendant(root, "licenseType")),
    }


def _reference(element: ET.Element | None, kind: str) -> dict[str, Any]:
    if element is None:
        return _empty_ref(kind)
    return {
        "type": kind,
        "refObjectId": element.get("refObjectId"),
        "shortDescription": _join_texts(_lang_elements(element, "shortDescription")),
    }


def _empty_ref(kind: str) -> dict[str, Any]:
    return {"type": kind, "refObjectId": None, "shortDescription": ""}


def _dataset_name(data_info: ET.Element | None, fallback: str) -> str:
    values = _name_lang(data_info)
    for language in ("en", "zh"):
        for item in values:
            if item["lang"] == language and item["text"]:
                return item["text"]
    return values[0]["text"] if values else fallback


def _name_lang(data_info: ET.Element | None) -> list[dict[str, str]]:
    name = _child(data_info, "name")
    if name is None:
        name = _child(data_info, "shortName")
    if name is None:
        return []
    base_names = _lang_elements(name, "baseName")
    return base_names or _element_lang(name)


def _field_lang(
    data_info: ET.Element | None, field: str
) -> list[dict[str, str]]:
    element = _child(data_info, field)
    return _element_lang(element) if element is not None else []


def _classification(data_info: ET.Element | None) -> list[str]:
    if data_info is None:
        return []
    container = _child(data_info, "classificationInformation")
    if container is None:
        return []
    return [
        _text(item)
        for item in container.iter()
        if (_matches(item, "class") or _matches(item, "category")) and _text(item)
    ]


def _lang_elements(parent: ET.Element | None, name: str) -> list[dict[str, str]]:
    if parent is None:
        return []
    return [item for element in _children(parent, name) for item in _element_lang(element)]


def _element_lang(element: ET.Element) -> list[dict[str, str]]:
    value = _text(element)
    return [{"lang": element.get(_XML_LANG, "en"), "text": value}] if value else []


def _join_texts(values: list[dict[str, str]]) -> str:
    return "\n".join(item["text"] for item in values if item["text"])


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _matches(element: ET.Element, name: str) -> bool:
    return _local(element.tag) == name and _namespace(element.tag) in _KNOWN_NAMESPACES


def _child(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    return next((item for item in parent if _matches(item, name)), None)


def _children(parent: ET.Element | None, name: str) -> list[ET.Element]:
    if parent is None:
        return []
    return [item for item in parent if _matches(item, name)]


def _path(parent: ET.Element | None, *names: str) -> ET.Element | None:
    for name in names:
        parent = _child(parent, name)
    return parent


def _first_descendant(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    return next((item for item in parent.iter() if _matches(item, name)), None)


def _descendants(parent: ET.Element | None, name: str) -> list[ET.Element]:
    if parent is None:
        return []
    return [item for item in parent.iter() if _matches(item, name)]


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _boolean(value: Any, default: bool) -> bool:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return default


def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}
