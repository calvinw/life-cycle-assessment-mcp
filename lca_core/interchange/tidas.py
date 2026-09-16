"""Tiangong TIDAS JSON ZIP to PRISM workspace conversion.

TIDAS JSON encodes the same ILCD schema `ilcd.py` already imports, using a
Badgerfish-style JSON convention instead of XML: an XML attribute becomes a
JSON key prefixed with `@` (e.g. `@refObjectId`), element text becomes
`#text` (or a bare scalar when the element has no attributes/children), and
XML namespace prefixes are kept as literal key prefixes (`common:UUID`).

This module mirrors `ilcd.py`'s field-mapping logic field-for-field. Only the
navigation primitives at the bottom differ (dict/list traversal instead of
`xml.etree.ElementTree`); `_convert`/`_payload`/`_validate_references` are
intentionally structured the same way as their `ilcd.py` counterparts so the
two stay easy to compare.

Grounded in a real Tiangong Task Center export
(`tests/fixtures/tidas_tiangong_export.zip`), not just the official schema
samples — see `TIDAS_IMPORT_EXPORT_PLAN.md` for what was verified and how.
"""

from __future__ import annotations

import json
import re
import zipfile
from typing import Any

from .archive import open_safe_zip
from .errors import InterchangeError
from .ilcd import DATASET_FOLDERS, FOLDER_DATASETS

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
TIDAS_MANIFEST_FORMAT = "tiangong-tidas-package"
TIDAS_MANIFEST_NAME = "manifest.json"


def is_tidas_package(package: bytes, names: set[str]) -> bool:
    """Format-detection check: does this ZIP look like a TIDAS package?

    Primary signal is `manifest.json` whose `format` field is the Tiangong
    literal `"tiangong-tidas-package"` (confirmed from a real export) — the
    filename alone isn't enough, since some other tool's export could also
    happen to ship a `manifest.json`. Falls back to a root-level TIDAS
    folder layout (a known dataset folder holding a `.json` member) for
    manifest-less exports, mirroring `ilcd.has_root_level_ilcd_layout`.
    """
    if _peek_manifest_format(package, names) == TIDAS_MANIFEST_FORMAT:
        return True
    return _has_root_level_tidas_layout(names)


def _peek_manifest_format(package: bytes, names: set[str]) -> str | None:
    """Best-effort read of manifest.json's `format` field for detection only.

    Must not raise on a malformed manifest.json belonging to some other
    tool — `_read_manifest` is what raises, once we've committed to parsing
    this package as TIDAS.
    """
    if TIDAS_MANIFEST_NAME not in names:
        return None
    try:
        archive = open_safe_zip(package)
        with archive:
            data = json.loads(archive.read(TIDAS_MANIFEST_NAME))
    except Exception:
        return None
    return data.get("format") if isinstance(data, dict) else None


def _has_root_level_tidas_layout(names: set[str]) -> bool:
    return any(
        name.endswith(".json") and name.count("/") == 1 and name.split("/", 1)[0] in FOLDER_DATASETS
        for name in names
    )


def preview_tidas(package: bytes) -> dict[str, Any]:
    """Read a Tiangong TIDAS JSON package and return normalized PRISM preview rows."""
    archive = open_safe_zip(package)
    warnings: list[dict[str, Any]] = []
    parsed: list[tuple[str, Any, str]] = []
    with archive:
        names = {info.filename for info in archive.infolist()}
        manifest = _read_manifest(archive, names)
        if manifest is not None:
            entries = _entries_from_manifest(manifest)
        else:
            entries = _entries_from_folder_scan(names, warnings)
        for table, file_path in entries:
            kind = FOLDER_DATASETS.get(table)
            if kind is None:
                warnings.append(
                    _warning("UNSUPPORTED_PACKAGE_ENTRY", f"Ignored '{file_path}'.", path=file_path)
                )
                continue
            expected_root = DATASET_FOLDERS[kind][1]
            root = _read_json_member(archive, file_path, expected_root)
            parsed.append((kind, root, file_path))

    if not parsed:
        raise InterchangeError(
            "EMPTY_TIDAS_PACKAGE", "The package contains no supported TIDAS datasets."
        )

    rows: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for kind, root, path in parsed:
        source_id = _required_uuid(root, path)
        if source_id in source_ids:
            raise InterchangeError(
                "DUPLICATE_TIDAS_ID",
                f"The package contains duplicate dataset id '{source_id}'.",
                details={"dataset_id": source_id},
            )
        source_ids.add(source_id)
        rows.append(_convert(root, kind, source_id))

    _validate_references(rows, warnings)
    rows.sort(key=lambda row: (row["type"], row["name"].casefold(), row["id"]))
    summary = {kind: 0 for kind in DATASET_FOLDERS}
    for row in rows:
        summary[row["type"]] += 1
    return {
        "format": "tidas-json",
        "valid": True,
        "summary": summary,
        "datasets": rows,
        "matches": [],
        "warnings": warnings,
        "errors": [],
    }


def _read_manifest(archive: zipfile.ZipFile, names: set[str]) -> dict[str, Any] | None:
    if TIDAS_MANIFEST_NAME not in names:
        return None
    try:
        raw = archive.read(TIDAS_MANIFEST_NAME)
        data = json.loads(raw)
    except (KeyError, UnicodeError, ValueError) as exc:
        raise InterchangeError(
            "INVALID_TIDAS_MANIFEST", "manifest.json is not valid JSON.", status_code=400
        ) from exc
    if not isinstance(data, dict) or data.get("format") != TIDAS_MANIFEST_FORMAT:
        return None
    return data


def _entries_from_manifest(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise InterchangeError(
            "INVALID_TIDAS_MANIFEST", "manifest.json has no 'entries' array.", status_code=400
        )
    result: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        table = entry.get("table")
        file_path = entry.get("file_path")
        if isinstance(table, str) and isinstance(file_path, str):
            result.append((table, file_path))
    return result


def _entries_from_folder_scan(
    names: set[str], warnings: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    warnings.append(
        _warning(
            "TIDAS_MISSING_MANIFEST",
            "No manifest.json found; falling back to folder-name detection.",
        )
    )
    result: list[tuple[str, str]] = []
    for name in sorted(names):
        if name.endswith("/") or not name.endswith(".json") or name == TIDAS_MANIFEST_NAME:
            continue
        parts = name.split("/")
        if len(parts) != 2:
            warnings.append(_warning("UNSUPPORTED_PACKAGE_ENTRY", f"Ignored '{name}'.", path=name))
            continue
        result.append((parts[0], name))
    return result


def _read_json_member(archive: zipfile.ZipFile, path: str, expected_root: str) -> Any:
    """Parse a TIDAS JSON member and return the payload under `expected_root`.

    A real Tiangong export can carry an extra top-level sibling key next to
    the dataset root (confirmed: `{"json_tg": {}, "lifeCycleModelDataSet":
    {...}}` in a real downloaded package) — look the dataset root up by
    name instead of assuming it's the file's only top-level key.
    """
    try:
        raw = archive.read(path)
        data = json.loads(raw)
    except (KeyError, UnicodeError, ValueError) as exc:
        raise InterchangeError(
            "INVALID_TIDAS_JSON",
            f"'{path}' is not valid TIDAS JSON.",
            details={"path": path},
            status_code=400,
        ) from exc
    if not isinstance(data, dict) or expected_root not in data:
        raise InterchangeError(
            "TIDAS_TYPE_MISMATCH",
            f"'{path}' does not contain a {expected_root}.",
            details={"path": path, "actual_keys": list(data) if isinstance(data, dict) else None},
        )
    return data[expected_root]


def _required_uuid(root: Any, path: str) -> str:
    node = _first_descendant(root, "UUID")
    value = _text(node)
    if not value:
        raise InterchangeError(
            "MISSING_TIDAS_UUID", f"'{path}' has no UUID.", details={"path": path}
        )
    if not _UUID_RE.match(value):
        raise InterchangeError(
            "INVALID_TIDAS_UUID",
            f"'{path}' has an invalid UUID.",
            details={"path": path, "uuid": value},
        )
    return value


def _convert(root: Any, kind: str, source_id: str) -> dict[str, Any]:
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
    description_field = "sourceDescriptionOrComment" if kind == "source" else "generalComment"
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
    root: Any,
    kind: str,
    information: Any,
    data_info: Any,
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
                    "referenceToReferenceUnit": _integer(
                        _text(_child(quantitative, "referenceToReferenceUnit"))
                    )
                },
            },
            "modellingAndValidation": {"complianceDeclarations": []},
            "administrativeInformation": admin,
            "units": [
                {
                    "dataSetInternalID": _integer(_attr(unit, "dataSetInternalID")),
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
                    "name": {
                        "baseName": _name_lang(data_info),
                        "treatmentStandardsRoutes": [],
                        "mixAndLocationTypes": [],
                    },
                    "classification": classification,
                    "casNumber": _text(_child(data_info, "CASNumber")),
                    "sumFormula": _text(_child(data_info, "sumFormula")),
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceFlowProperty": _integer(
                        _text(_child(quantitative, "referenceToReferenceFlowProperty"))
                    )
                },
            },
            "modellingAndValidation": {
                "typeOfDataSet": _text(_child(method, "typeOfDataSet")),
                "complianceDeclarations": [],
            },
            "administrativeInformation": admin,
            "flowProperties": [
                {
                    "dataSetInternalID": _integer(_attr(item, "dataSetInternalID")),
                    "referenceToFlowPropertyDataSet": _reference(
                        _child(item, "referenceToFlowPropertyDataSet"), "flow_property"
                    ),
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
                    "name": {
                        "baseName": _name_lang(data_info),
                        "treatmentStandardsRoutes": [],
                        "mixAndLocationTypes": [],
                    },
                    "classification": classification,
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceFlow": _integer(
                        _text(_child(quantitative, "referenceToReferenceFlow"))
                    )
                },
                "time": {
                    "referenceYear": _integer(
                        _text(_first_descendant(_child(information, "time"), "referenceYear"))
                    )
                },
                "geography": {"location": (_attr(location, "location") or "") if location is not None else ""},
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
                    "dataSetInternalID": _integer(_attr(item, "dataSetInternalID")),
                    "referenceToFlowDataSet": _reference(_child(item, "referenceToFlowDataSet"), "flow"),
                    "exchangeDirection": _text(_child(item, "exchangeDirection")),
                    "meanAmount": _float(
                        _text(_child(item, "meanAmount")), _float(_attr(item, "amount"), 0.0)
                    ),
                    "resultingAmount": _float(
                        _text(_child(item, "resultingAmount")), _float(_attr(item, "amount"), 0.0)
                    ),
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
            upstream = _integer(_attr(instance, "dataSetInternalID"))
            for downstream in _descendants(instance, "downstreamProcess"):
                connections.append(
                    {"fromInstanceId": upstream, "toInstanceId": _integer(_attr(downstream, "id"))}
                )
        return {
            "modelInformation": {
                "dataSetInformation": {
                    "name": {
                        "baseName": _name_lang(data_info),
                        "treatmentStandardsRoutes": [],
                        "mixAndLocationTypes": [],
                    },
                    "classification": classification,
                    "generalComment": general_comment,
                },
                "quantitativeReference": {
                    "referenceToReferenceProcess": _integer(
                        _text(_child(quantitative, "referenceToReferenceProcess"))
                    )
                },
            },
            "modellingAndValidation": {"complianceDeclarations": []},
            "administrativeInformation": _extended_admin(root, admin),
            "processInstances": [
                {
                    "dataSetInternalID": _integer(_attr(item, "dataSetInternalID")),
                    "referenceToProcess": _reference(_child(item, "referenceToProcess"), "process"),
                    "multiplicationFactor": _float(_attr(item, "multiplicationFactor"), 1.0),
                }
                for item in instances
            ],
            "connections": connections,
        }

    if kind == "source":
        source_comment = _lang_elements(data_info, "sourceDescriptionOrComment")
        return {
            "sourceInformation": {
                "dataSetInformation": {
                    "shortName": _field_lang(data_info, "shortName"),
                    "classification": classification,
                    "sourceCitation": _text(_child(data_info, "sourceCitation")),
                    "publicationType": _text(_child(data_info, "publicationType")),
                    "sourceDescriptionOrComment": source_comment,
                    "referenceToContact": _reference(_child(data_info, "referenceToContact"), "contact"),
                }
            },
            "administrativeInformation": admin,
        }

    if kind == "contact":
        short_name = _field_lang(data_info, "shortName")
        full_name = _field_lang(data_info, "name")
        contact_comment = _lang_elements(data_info, "contactDescriptionOrComment")
        return {
            "contactInformation": {
                "dataSetInformation": {
                    "shortName": short_name,
                    "name": full_name or short_name,
                    "classification": classification,
                    "email": _text(_child(data_info, "email")),
                    "wwwAddress": _text(_child(data_info, "WWWAddress")),
                    "centralContactPoint": _lang_elements(data_info, "centralContactPoint"),
                    "contactAddress": _text(_child(data_info, "contactAddress")),
                    "telephone": _text(_child(data_info, "telephone")),
                    "telefax": _text(_child(data_info, "telefax")),
                    "generalComment": contact_comment or general_comment,
                    "referenceToContact": [],
                }
            },
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
                    "INVALID_TIDAS_PROCESS_INSTANCE_ID",
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


def _administrative_information(root: Any) -> dict[str, Any]:
    ownership = _first_descendant(root, "referenceToOwnershipOfDataSet")
    return {
        "referenceToOwnershipOfDataSet": _reference(ownership, "contact"),
        "dataSetVersion": _text(_first_descendant(root, "dataSetVersion")) or "01.01.000",
        "permanentDataSetURI": _text(_first_descendant(root, "permanentDataSetURI")),
        "timeStamp": _text(_first_descendant(root, "timeStamp")),
    }


def _extended_admin(root: Any, admin: dict[str, Any]) -> dict[str, Any]:
    goal = _first_descendant(root, "commissionerAndGoal")
    return {
        **admin,
        "referenceToCommissioner": _reference(
            _first_descendant(goal, "referenceToCommissioner"), "contact"
        ),
        "intendedApplications": _lang_elements(goal, "intendedApplications"),
        "referenceToPersonOrEntityGeneratingTheDataSet": _reference(
            _first_descendant(root, "referenceToPersonOrEntityGeneratingTheDataSet"),
            "contact",
        ),
        "copyright": _boolean(_text(_first_descendant(root, "copyright")), False),
        "licenseType": _text(_first_descendant(root, "licenseType")),
    }


def _reference(node: Any, kind: str) -> dict[str, Any]:
    if node is None:
        return _empty_ref(kind)
    return {
        "type": kind,
        "refObjectId": _attr(node, "refObjectId"),
        "shortDescription": _join_texts(_lang_elements(node, "shortDescription")),
    }


def _empty_ref(kind: str) -> dict[str, Any]:
    return {"type": kind, "refObjectId": None, "shortDescription": ""}


def _dataset_name(data_info: Any, fallback: str) -> str:
    values = _name_lang(data_info)
    for language in ("en", "zh"):
        for item in values:
            if item["lang"] == language and item["text"]:
                return item["text"]
    return values[0]["text"] if values else fallback


def _name_lang(data_info: Any) -> list[dict[str, str]]:
    name = _child(data_info, "name")
    if name is None:
        name = _child(data_info, "shortName")
    if name is None:
        return []
    base_names = _lang_elements(name, "baseName")
    return base_names or _element_lang(name)


def _field_lang(data_info: Any, field: str) -> list[dict[str, str]]:
    node = _child(data_info, field)
    return _element_lang(node) if node is not None else []


def _classification(data_info: Any) -> list[str]:
    if data_info is None:
        return []
    container = _child(data_info, "classificationInformation")
    if container is None:
        return []
    return [
        _text(value)
        for local, value in _iter_named(container)
        if local in ("class", "category") and _text(value)
    ]


def _lang_elements(parent: Any, name: str) -> list[dict[str, str]]:
    if parent is None:
        return []
    return [item for node in _children(parent, name) for item in _element_lang(node)]


def _element_lang(node: Any) -> list[dict[str, str]]:
    value = _text(node)
    return [{"lang": _attr(node, "xml:lang") or "en", "text": value}] if value else []


def _join_texts(values: list[dict[str, str]]) -> str:
    return "\n".join(item["text"] for item in values if item["text"])


def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


# --- Badgerfish JSON navigation primitives -----------------------------
#
# These mirror the ElementTree-based primitives in ilcd.py (_child,
# _children, _text, _first_descendant, _descendants, _path) closely enough
# that the field-mapping logic above reads almost identically to ilcd.py's.
# `_attr` has no ElementTree equivalent by name; it replaces `element.get(...)`
# calls (an XML attribute read).


def _is_attr_or_text(key: str) -> bool:
    return key.startswith("@") or key == "#text"


def _local(key: str) -> str:
    """Strip an XML namespace prefix from a Badgerfish key: 'common:UUID' -> 'UUID'."""
    return key.split(":", 1)[-1]


def _child(parent: Any, name: str) -> Any:
    """First child node matching `name` (bare object, or first item of an array)."""
    if not isinstance(parent, dict):
        return None
    for key, value in parent.items():
        if _is_attr_or_text(key):
            continue
        if _local(key) == name:
            if isinstance(value, list):
                return value[0] if value else None
            return value
    return None


def _children(parent: Any, name: str) -> list[Any]:
    """All child nodes matching `name`, normalizing bare-object-vs-array to a list."""
    if not isinstance(parent, dict):
        return []
    for key, value in parent.items():
        if _is_attr_or_text(key):
            continue
        if _local(key) == name:
            if isinstance(value, list):
                return [item for item in value if item is not None]
            return [value] if value is not None else []
    return []


def _path(parent: Any, *names: str) -> Any:
    for name in names:
        parent = _child(parent, name)
    return parent


def _iter_named(node: Any):
    """Depth-first (local_name, value_node) pairs for every node in the tree,
    in document order — mirrors `ET.Element.iter()` combined with tag matching.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if _is_attr_or_text(key):
                continue
            local = _local(key)
            items = value if isinstance(value, list) else [value]
            for item in items:
                if item is None:
                    continue
                yield local, item
                yield from _iter_named(item)


def _descendants(parent: Any, name: str) -> list[Any]:
    return [value for local, value in _iter_named(parent) if local == name]


def _first_descendant(parent: Any, name: str) -> Any:
    for local, value in _iter_named(parent):
        if local == name:
            return value
    return None


def _text(node: Any) -> str:
    """Text content of a Badgerfish node: dict with #text, or a bare scalar."""
    if node is None:
        return ""
    if isinstance(node, dict):
        if "#text" in node:
            return str(node["#text"]).strip()
        return ""
    if isinstance(node, bool):
        return ""
    if isinstance(node, (str, int, float)):
        return str(node).strip()
    return ""


def _attr(node: Any, name: str) -> Any:
    if isinstance(node, dict):
        return node.get(f"@{name}")
    return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
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
