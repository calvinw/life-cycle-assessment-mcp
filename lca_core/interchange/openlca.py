"""PRISM bundle ↔ openLCA JSON-LD package conversion.

The implementation targets version 2 of the public openLCA schema package.
It uses plain dictionaries so the LCA service can remain on Python 3.11 while
the current ``olca-schema`` Python package requires Python 3.12.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import posixpath
import re
import stat
import uuid
import zipfile
from collections.abc import Iterable
from typing import Any

from .errors import InterchangeError

SCHEMA_VERSION = 2
MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_ENTRIES = 5_000

DATASET_FOLDERS = {
    "model": ("product_systems", "ProductSystem"),
    "process": ("processes", "Process"),
    "flow": ("flows", "Flow"),
    "flow_property": ("flow_properties", "FlowProperty"),
    "unit_group": ("unit_groups", "UnitGroup"),
    "source": ("sources", "Source"),
    "contact": ("actors", "Actor"),
}
FOLDER_DATASETS = {folder: kind for kind, (folder, _) in DATASET_FOLDERS.items()}
TYPE_DATASETS = {olca_type: kind for kind, (_, olca_type) in DATASET_FOLDERS.items()}
PLURAL_KEYS = {
    "model": "models",
    "process": "processes",
    "flow": "flows",
    "flow_property": "flow_properties",
    "unit_group": "unit_groups",
    "source": "sources",
    "contact": "contacts",
}

_PRISM_EXTENSION = "prismInterchange"
_UNIT_NAMESPACE = uuid.UUID("52b65d41-e0dd-4e16-bd40-ed572ea24547")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def export_openlca(bundle: dict[str, Any]) -> bytes:
    """Convert a complete PRISM dataset bundle to an openLCA JSON-LD ZIP."""
    records = _read_bundle(bundle)
    _validate_prism_references(records)
    by_id = {row["id"]: row for row in records}

    entries: dict[str, bytes] = {
        "olca-schema.json": b'{"version":2}\n',
    }
    for row in sorted(records, key=lambda item: (item["type"], item["id"])):
        entity = _to_openlca(row, by_id)
        extension = {
            "datasetType": row["type"],
            "payload": row["payload"],
            "entityHash": _entity_hash(entity),
        }
        entity.setdefault("otherProperties", {})[_PRISM_EXTENSION] = extension
        folder = DATASET_FOLDERS[row["type"]][0]
        entries[f"{folder}/{row['id']}.json"] = _json_bytes(entity)

    return _write_zip(entries)


def preview_openlca(
    package: bytes,
    existing_catalog: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read an openLCA JSON-LD ZIP and return normalized PRISM preview rows."""
    entities, warnings = _read_openlca_zip(package)
    context = _ImportContext(entities)
    datasets = []
    for entity in entities:
        kind = TYPE_DATASETS.get(entity.get("@type"))
        if kind is None:
            continue
        row, row_warnings = _from_openlca(entity, kind, context)
        warnings.extend(row_warnings)
        datasets.append(row)

    datasets.sort(key=lambda row: (row["type"], row["name"].casefold(), row["id"]))
    _apply_catalog_decisions(datasets, existing_catalog or [])
    _warn_unresolved_import_references(datasets, warnings)

    summary = {kind: 0 for kind in DATASET_FOLDERS}
    for row in datasets:
        summary[row["type"]] += 1
    return {
        "format": "openlca-json-ld",
        "valid": True,
        "summary": summary,
        "datasets": datasets,
        "matches": [
            {
                "temporary_id": row["temporary_id"],
                "candidate_dataset_id": row["candidate_dataset_id"],
                "confidence": row["match_confidence"],
                "reason": row["match_reason"],
            }
            for row in datasets
            if row.get("candidate_dataset_id")
        ],
        "warnings": warnings,
        "errors": [],
    }


def _read_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict):
        raise InterchangeError(
            "MALFORMED_BUNDLE", "The export request must be a JSON object.", status_code=400
        )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, plural in PLURAL_KEYS.items():
        values = bundle.get(plural, [])
        if not isinstance(values, list):
            raise InterchangeError(
                "MALFORMED_BUNDLE",
                f"'{plural}' must be an array.",
                details={"field": plural},
                status_code=400,
            )
        for index, raw in enumerate(values):
            if not isinstance(raw, dict):
                raise InterchangeError(
                    "MALFORMED_DATASET",
                    f"{plural}[{index}] must be an object.",
                    status_code=400,
                )
            row = copy.deepcopy(raw)
            row_id = row.get("id")
            if not isinstance(row_id, str) or not _UUID_RE.match(row_id):
                raise InterchangeError(
                    "INVALID_DATASET_ID",
                    f"{plural}[{index}] must have a UUID id.",
                    details={"field": f"{plural}[{index}].id"},
                )
            if row_id in seen:
                raise InterchangeError(
                    "DUPLICATE_DATASET_ID",
                    f"Dataset id '{row_id}' occurs more than once.",
                    details={"dataset_id": row_id},
                )
            seen.add(row_id)
            if row.get("type", kind) != kind:
                raise InterchangeError(
                    "DATASET_TYPE_MISMATCH",
                    f"Dataset '{row_id}' is in '{plural}' but has type '{row.get('type')}'.",
                    details={"dataset_id": row_id, "expected_type": kind},
                )
            if not isinstance(row.get("name"), str) or not row["name"].strip():
                raise InterchangeError(
                    "MISSING_DATASET_NAME",
                    f"Dataset '{row_id}' must have a name.",
                    details={"dataset_id": row_id},
                )
            if not isinstance(row.get("payload", {}), dict):
                raise InterchangeError(
                    "INVALID_DATASET_PAYLOAD",
                    f"Dataset '{row_id}' payload must be an object.",
                    details={"dataset_id": row_id},
                )
            row["type"] = kind
            row.setdefault("description", None)
            row.setdefault("payload", {})
            records.append(row)
    if not records:
        raise InterchangeError("EMPTY_BUNDLE", "The export bundle contains no datasets.")
    return records


def _validate_prism_references(records: list[dict[str, Any]]) -> None:
    by_id = {row["id"]: row for row in records}

    def require(reference: Any, expected: str, owner: str, path: str) -> None:
        if not isinstance(reference, dict):
            return
        target_id = reference.get("refObjectId")
        if target_id is None:
            return
        target = by_id.get(target_id)
        if target is None or target["type"] != expected:
            raise InterchangeError(
                "UNRESOLVED_DATASET_REFERENCE",
                f"Dataset '{owner}' has an unresolved {expected} reference.",
                details={"dataset_id": owner, "reference_id": target_id, "path": path},
            )

    for row in records:
        payload = row["payload"]
        if row["type"] == "process":
            for index, exchange in enumerate(payload.get("exchanges", [])):
                require(
                    exchange.get("referenceToFlowDataSet"),
                    "flow",
                    row["id"],
                    f"exchanges[{index}].referenceToFlowDataSet",
                )
        elif row["type"] == "flow":
            for index, factor in enumerate(payload.get("flowProperties", [])):
                require(
                    factor.get("referenceToFlowPropertyDataSet"),
                    "flow_property",
                    row["id"],
                    f"flowProperties[{index}].referenceToFlowPropertyDataSet",
                )
        elif row["type"] == "flow_property":
            require(
                _dig(payload, "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup"),
                "unit_group",
                row["id"],
                "flowPropertiesInformation.quantitativeReference.referenceToReferenceUnitGroup",
            )
        elif row["type"] == "model":
            for index, instance in enumerate(payload.get("processInstances", [])):
                require(
                    instance.get("referenceToProcess"),
                    "process",
                    row["id"],
                    f"processInstances[{index}].referenceToProcess",
                )


def _to_openlca(row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    kind = row["type"]
    payload = row["payload"]
    entity = _root(row, DATASET_FOLDERS[kind][1])
    if kind == "contact":
        info = _dig(payload, "contactInformation", "dataSetInformation") or {}
        entity.update(
            address=info.get("contactAddress") or None,
            email=info.get("email") or None,
            telefax=info.get("telefax") or None,
            telephone=info.get("telephone") or None,
            website=info.get("wwwAddress") or None,
        )
    elif kind == "source":
        info = _dig(payload, "sourceInformation", "dataSetInformation") or {}
        entity.update(
            textReference=info.get("sourceCitation") or row.get("description") or None,
            url=_dig(payload, "administrativeInformation", "permanentDataSetURI") or None,
        )
    elif kind == "unit_group":
        units = payload.get("units", [])
        reference_id = _dig(
            payload, "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit"
        )
        entity["units"] = [
            {
                "@type": "Unit",
                "@id": _unit_id(row["id"], unit.get("dataSetInternalID", index + 1)),
                "name": unit.get("name") or f"unit-{index + 1}",
                "conversionFactor": _number(unit.get("meanValue"), 1.0),
                "isRefUnit": unit.get("dataSetInternalID", index + 1) == reference_id,
            }
            for index, unit in enumerate(units)
            if isinstance(unit, dict)
        ]
    elif kind == "flow_property":
        unit_group = _dig(
            payload, "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup"
        )
        entity.update(
            flowPropertyType="PHYSICAL_QUANTITY",
            unitGroup=_ref(unit_group, "UnitGroup", by_id),
        )
    elif kind == "flow":
        info = _dig(payload, "flowInformation", "dataSetInformation") or {}
        reference_id = _dig(
            payload, "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty"
        )
        entity.update(
            cas=info.get("casNumber") or None,
            formula=info.get("sumFormula") or None,
            flowType=_flow_type(_dig(payload, "modellingAndValidation", "typeOfDataSet")),
            flowProperties=[
                {
                    "@type": "FlowPropertyFactor",
                    "conversionFactor": _number(factor.get("meanValue"), 1.0),
                    "isRefFlowProperty": factor.get("dataSetInternalID", index + 1) == reference_id,
                    "flowProperty": _ref(
                        factor.get("referenceToFlowPropertyDataSet"), "FlowProperty", by_id
                    ),
                }
                for index, factor in enumerate(payload.get("flowProperties", []))
                if isinstance(factor, dict)
            ],
        )
    elif kind == "process":
        _fill_process(entity, row, by_id)
    elif kind == "model":
        _fill_product_system(entity, row, by_id)
    return _without_none(entity)


def _root(row: dict[str, Any], olca_type: str) -> dict[str, Any]:
    payload = row["payload"]
    admin = payload.get("administrativeInformation", {})
    classification = _classification(payload, row["type"])
    return _without_none(
        {
            "@type": olca_type,
            "@id": row["id"],
            "name": row["name"],
            "description": row.get("description"),
            "category": "/".join(classification) if classification else None,
            "lastChange": admin.get("timeStamp"),
            "version": _openlca_version(admin.get("dataSetVersion")),
        }
    )


def _fill_process(
    entity: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    qref = _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    exchanges = []
    for index, exchange in enumerate(payload.get("exchanges", [])):
        if not isinstance(exchange, dict):
            continue
        flow_ref = exchange.get("referenceToFlowDataSet")
        flow = by_id.get(flow_ref.get("refObjectId")) if isinstance(flow_ref, dict) else None
        fp_ref, unit_ref = _flow_amount_refs(flow, by_id)
        internal_id = exchange.get("dataSetInternalID", index + 1)
        exchanges.append(
            _without_none(
                {
                    "@type": "Exchange",
                    "internalId": internal_id,
                    "flow": _ref(flow_ref, "Flow", by_id),
                    "flowProperty": fp_ref,
                    "unit": unit_ref,
                    "amount": _number(
                        exchange.get("resultingAmount", exchange.get("meanAmount")), 0.0
                    ),
                    "isInput": exchange.get("exchangeDirection") == "Input",
                    "isQuantitativeReference": internal_id == qref,
                    "description": _text(exchange.get("generalComment")) or None,
                }
            )
        )
    info = payload.get("processInformation", {})
    admin = payload.get("administrativeInformation", {})
    modelling = payload.get("modellingAndValidation", {})
    sources = []
    source = modelling.get("referenceToDataSource")
    if isinstance(source, dict) and source.get("refObjectId"):
        sources.append(_ref(source, "Source", by_id))
    entity.update(
        exchanges=exchanges,
        lastInternalId=max((item.get("internalId", 0) for item in exchanges), default=0),
        processType=(
            "LCI_RESULT" if modelling.get("typeOfDataSet") == "LCI result" else "UNIT_PROCESS"
        ),
        processDocumentation=_without_none(
            {
                "@type": "ProcessDocumentation",
                "creationDate": admin.get("timeStamp"),
                "geographyDescription": _dig(info, "geography", "location") or None,
                "intendedApplication": _text(admin.get("intendedApplications")) or None,
                "isCopyrightProtected": admin.get("copyright"),
                "sources": sources or None,
                "dataGenerator": _ref(
                    admin.get("referenceToPersonOrEntityGeneratingTheDataSet"), "Actor", by_id
                ),
                "dataSetOwner": _ref(
                    admin.get("referenceToOwnershipOfDataSet"), "Actor", by_id
                ),
            }
        ),
    )


def _fill_product_system(
    entity: dict[str, Any], row: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    payload = row["payload"]
    instances = [item for item in payload.get("processInstances", []) if isinstance(item, dict)]
    by_instance = {item.get("dataSetInternalID"): item for item in instances}
    process_refs = [
        _ref(item.get("referenceToProcess"), "Process", by_id) for item in instances
    ]
    process_refs = [item for item in process_refs if item is not None]
    links = []
    for connection in payload.get("connections", []):
        if not isinstance(connection, dict):
            continue
        provider_instance = by_instance.get(connection.get("fromInstanceId"))
        consumer_instance = by_instance.get(connection.get("toInstanceId"))
        if not provider_instance or not consumer_instance:
            continue
        provider_ref = provider_instance.get("referenceToProcess")
        consumer_ref = consumer_instance.get("referenceToProcess")
        provider = by_id.get(provider_ref.get("refObjectId")) if isinstance(provider_ref, dict) else None
        consumer = by_id.get(consumer_ref.get("refObjectId")) if isinstance(consumer_ref, dict) else None
        flow_ref, consumer_exchange_id = _linked_flow(provider, consumer)
        links.append(
            _without_none(
                {
                    "@type": "ProcessLink",
                    "provider": _ref(provider_ref, "Process", by_id),
                    "process": _ref(consumer_ref, "Process", by_id),
                    "flow": _ref(flow_ref, "Flow", by_id),
                    "exchange": (
                        {"@type": "ExchangeRef", "internalId": consumer_exchange_id}
                        if consumer_exchange_id is not None
                        else None
                    ),
                }
            )
        )

    reference_instance_id = _dig(
        payload, "modelInformation", "quantitativeReference", "referenceToReferenceProcess"
    )
    reference_instance = by_instance.get(reference_instance_id)
    reference_process_ref = (
        reference_instance.get("referenceToProcess") if reference_instance else None
    )
    reference_process = (
        by_id.get(reference_process_ref.get("refObjectId"))
        if isinstance(reference_process_ref, dict)
        else None
    )
    reference_exchange = _reference_exchange(reference_process)
    flow = None
    if reference_exchange:
        flow_ref = reference_exchange.get("referenceToFlowDataSet")
        flow = by_id.get(flow_ref.get("refObjectId")) if isinstance(flow_ref, dict) else None
    fp_ref, unit_ref = _flow_amount_refs(flow, by_id)
    multiplier = _number(reference_instance.get("multiplicationFactor"), 1.0) if reference_instance else 1.0
    target_amount = (
        _number(reference_exchange.get("resultingAmount", reference_exchange.get("meanAmount")), 1.0)
        * multiplier
        if reference_exchange
        else multiplier
    )
    entity.update(
        processes=process_refs,
        processLinks=links,
        refProcess=_ref(reference_process_ref, "Process", by_id),
        refExchange=(
            {
                "@type": "ExchangeRef",
                "internalId": reference_exchange.get("dataSetInternalID"),
            }
            if reference_exchange
            else None
        ),
        targetAmount=target_amount,
        targetFlowProperty=fp_ref,
        targetUnit=unit_ref,
    )


def _read_openlca_zip(package: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(package) > MAX_PACKAGE_BYTES:
        raise InterchangeError(
            "PACKAGE_TOO_LARGE",
            "The compressed package exceeds the 25 MB limit.",
            details={"compressed_bytes": len(package), "limit_bytes": MAX_PACKAGE_BYTES},
            status_code=413,
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(package), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise InterchangeError(
            "INVALID_ZIP", "The uploaded file is not a valid ZIP package.", status_code=400
        ) from exc
    warnings: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise InterchangeError(
                "TOO_MANY_ARCHIVE_ENTRIES",
                "The package contains too many files.",
                details={"entries": len(infos), "limit": MAX_ENTRIES},
                status_code=413,
            )
        expanded = 0
        names = set()
        for info in infos:
            _validate_member(info)
            expanded += info.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise InterchangeError(
                    "EXPANDED_PACKAGE_TOO_LARGE",
                    "The expanded package exceeds the 250 MB limit.",
                    details={"expanded_bytes": expanded, "limit_bytes": MAX_EXPANDED_BYTES},
                    status_code=413,
                )
            names.add(info.filename)
        if "olca-schema.json" not in names:
            raise InterchangeError(
                "MISSING_OPENLCA_MANIFEST",
                "The ZIP does not contain olca-schema.json at its root.",
                status_code=400,
            )
        manifest = _read_json_member(archive, "olca-schema.json")
        if manifest.get("version") != SCHEMA_VERSION:
            raise InterchangeError(
                "UNSUPPORTED_OPENLCA_VERSION",
                f"Only openLCA schema package version {SCHEMA_VERSION} is supported.",
                details={"version": manifest.get("version")},
                status_code=400,
            )
        for info in infos:
            if info.is_dir() or info.filename == "olca-schema.json" or not info.filename.endswith(".json"):
                continue
            parts = info.filename.split("/")
            if len(parts) != 2 or parts[0] not in FOLDER_DATASETS:
                warnings.append(
                    _warning("UNSUPPORTED_PACKAGE_ENTRY", f"Ignored '{info.filename}'.", path=info.filename)
                )
                continue
            entity = _read_json_member(archive, info.filename)
            expected_type = DATASET_FOLDERS[FOLDER_DATASETS[parts[0]]][1]
            if entity.get("@type") != expected_type:
                raise InterchangeError(
                    "OPENLCA_TYPE_MISMATCH",
                    f"'{info.filename}' does not contain a {expected_type}.",
                    details={"path": info.filename, "actual_type": entity.get("@type")},
                )
            uid = entity.get("@id")
            if not isinstance(uid, str) or not uid:
                raise InterchangeError(
                    "MISSING_OPENLCA_ID",
                    f"'{info.filename}' has no @id.",
                    details={"path": info.filename},
                )
            if posixpath.basename(info.filename) != f"{uid}.json":
                warnings.append(
                    _warning(
                        "OPENLCA_FILENAME_ID_MISMATCH",
                        f"The filename for '{uid}' does not match its @id.",
                        path=info.filename,
                    )
                )
            entities.append(entity)
    if not entities:
        raise InterchangeError("EMPTY_OPENLCA_PACKAGE", "The package contains no supported datasets.")
    ids = [entity["@id"] for entity in entities]
    if len(ids) != len(set(ids)):
        raise InterchangeError("DUPLICATE_OPENLCA_ID", "The package contains duplicate dataset IDs.")
    return entities, warnings


class _ImportContext:
    def __init__(self, entities: list[dict[str, Any]]) -> None:
        self.by_id = {entity["@id"]: entity for entity in entities}
        self.unit_locations: dict[str, tuple[str, int]] = {}
        for group in entities:
            if group.get("@type") != "UnitGroup":
                continue
            for index, unit in enumerate(group.get("units", [])):
                if isinstance(unit, dict) and isinstance(unit.get("@id"), str):
                    self.unit_locations[unit["@id"]] = (group["@id"], index + 1)


def _from_openlca(
    entity: dict[str, Any], kind: str, context: _ImportContext
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    extension = (entity.get("otherProperties") or {}).get(_PRISM_EXTENSION)
    payload = None
    if isinstance(extension, dict) and extension.get("datasetType") == kind:
        if extension.get("entityHash") == _entity_hash(entity) and isinstance(extension.get("payload"), dict):
            payload = copy.deepcopy(extension["payload"])
        else:
            warnings.append(
                _warning(
                    "STALE_PRISM_EXTENSION",
                    f"'{entity.get('name') or entity['@id']}' changed after export; rebuilt it from openLCA fields.",
                    dataset_id=entity["@id"],
                )
            )
    if payload is None:
        payload = _generic_payload(entity, kind, context)
    name = entity.get("name") or entity["@id"]
    row = {
        "temporary_id": f"import:{kind}:{entity['@id']}",
        "source_id": entity["@id"],
        "id": entity["@id"] if _UUID_RE.match(entity["@id"]) else str(uuid.uuid5(_UNIT_NAMESPACE, entity["@id"])),
        "type": kind,
        "name": name,
        "description": entity.get("description") or "",
        "payload": payload,
        "decision": "create",
    }
    return row, warnings


def _generic_payload(entity: dict[str, Any], kind: str, context: _ImportContext) -> dict[str, Any]:
    admin = _import_admin(entity)
    if kind == "contact":
        return {
            "contactInformation": {"dataSetInformation": {
                "shortName": _lang(entity.get("name")), "name": _lang(entity.get("name")),
                "classification": _split_category(entity.get("category")), "email": entity.get("email") or "",
                "wwwAddress": entity.get("website") or "", "centralContactPoint": [],
                "contactAddress": entity.get("address") or "", "telephone": entity.get("telephone") or "",
                "telefax": entity.get("telefax") or "", "generalComment": _lang(entity.get("description")),
                "referenceToContact": [],
            }}, "administrativeInformation": admin,
        }
    if kind == "source":
        return {
            "sourceInformation": {"dataSetInformation": {
                "shortName": _lang(entity.get("name")), "classification": _split_category(entity.get("category")),
                "sourceCitation": entity.get("textReference") or "", "publicationType": "",
                "sourceDescriptionOrComment": _lang(entity.get("description")),
                "referenceToContact": _empty_ref("contact"),
            }}, "administrativeInformation": admin,
        }
    if kind == "unit_group":
        units = [item for item in entity.get("units", []) if isinstance(item, dict)]
        ref_index = next((i + 1 for i, unit in enumerate(units) if unit.get("isRefUnit")), None)
        return {
            "unitGroupInformation": {
                "dataSetInformation": {"name": _lang(entity.get("name")), "classification": _split_category(entity.get("category")), "generalComment": _lang(entity.get("description"))},
                "quantitativeReference": {"referenceToReferenceUnit": ref_index},
            },
            "modellingAndValidation": {"complianceDeclarations": []},
            "administrativeInformation": admin,
            "units": [{"dataSetInternalID": i + 1, "name": unit.get("name") or "", "meanValue": _number(unit.get("conversionFactor"), 1.0), "generalComment": []} for i, unit in enumerate(units)],
        }
    if kind == "flow_property":
        return {
            "flowPropertiesInformation": {
                "dataSetInformation": {"name": _lang(entity.get("name")), "classification": _split_category(entity.get("category")), "generalComment": _lang(entity.get("description"))},
                "quantitativeReference": {"referenceToReferenceUnitGroup": _prism_ref(entity.get("unitGroup"), "unit_group")},
            },
            "modellingAndValidation": {"referenceToDataSource": _empty_ref("source"), "complianceDeclarations": []},
            "administrativeInformation": admin,
        }
    if kind == "flow":
        factors = [item for item in entity.get("flowProperties", []) if isinstance(item, dict)]
        ref_index = next((i + 1 for i, factor in enumerate(factors) if factor.get("isRefFlowProperty")), None)
        return {
            "flowInformation": {
                "dataSetInformation": {"name": {"baseName": _lang(entity.get("name")), "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": _split_category(entity.get("category")), "casNumber": entity.get("cas") or "", "sumFormula": entity.get("formula") or "", "generalComment": _lang(entity.get("description"))},
                "quantitativeReference": {"referenceToReferenceFlowProperty": ref_index},
            },
            "modellingAndValidation": {"typeOfDataSet": _prism_flow_type(entity.get("flowType")), "complianceDeclarations": []},
            "administrativeInformation": admin,
            "flowProperties": [{"dataSetInternalID": i + 1, "referenceToFlowPropertyDataSet": _prism_ref(factor.get("flowProperty"), "flow_property"), "meanValue": _number(factor.get("conversionFactor"), 1.0), "generalComment": []} for i, factor in enumerate(factors)],
        }
    if kind == "process":
        documentation = entity.get("processDocumentation") or {}
        exchanges = [item for item in entity.get("exchanges", []) if isinstance(item, dict)]
        source_ref = (documentation.get("sources") or [None])[0]
        return {
            "processInformation": {
                "dataSetInformation": {"name": {"baseName": _lang(entity.get("name")), "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": _split_category(entity.get("category")), "generalComment": _lang(entity.get("description"))},
                "quantitativeReference": {"referenceToReferenceFlow": next((item.get("internalId") for item in exchanges if item.get("isQuantitativeReference")), None)},
                "time": {"referenceYear": None}, "geography": {"location": documentation.get("geographyDescription") or ""},
            },
            "modellingAndValidation": {"typeOfDataSet": "LCI result" if entity.get("processType") == "LCI_RESULT" else "Unit process, single operation", "dataCutOffAndCompletenessPrinciples": [], "referenceToDataSource": _prism_ref(source_ref, "source"), "annualSupplyOrProductionVolume": [], "complianceDeclarations": []},
            "administrativeInformation": {**admin, "referenceToCommissioner": _empty_ref("contact"), "intendedApplications": _lang(documentation.get("intendedApplication")), "referenceToPersonOrEntityGeneratingTheDataSet": _prism_ref(documentation.get("dataGenerator"), "contact"), "copyright": bool(documentation.get("isCopyrightProtected")), "licenseType": ""},
            "exchanges": [{"dataSetInternalID": item.get("internalId", i + 1), "referenceToFlowDataSet": _prism_ref(item.get("flow"), "flow"), "exchangeDirection": "Input" if item.get("isInput") else "Output", "meanAmount": _number(item.get("amount"), 0.0), "resultingAmount": _number(item.get("amount"), 0.0), "generalComment": _lang(item.get("description"))} for i, item in enumerate(exchanges)],
        }
    if kind == "model":
        process_refs = [item for item in entity.get("processes", []) if isinstance(item, dict)]
        id_by_process = {item.get("@id"): i + 1 for i, item in enumerate(process_refs)}
        ref_process = entity.get("refProcess") or {}
        connections = []
        for link in entity.get("processLinks", []):
            if not isinstance(link, dict):
                continue
            from_id = id_by_process.get(_ref_id(link.get("provider")))
            to_id = id_by_process.get(_ref_id(link.get("process")))
            if from_id and to_id:
                connections.append({"fromInstanceId": from_id, "toInstanceId": to_id})
        return {
            "modelInformation": {
                "dataSetInformation": {"name": {"baseName": _lang(entity.get("name")), "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": _split_category(entity.get("category")), "generalComment": _lang(entity.get("description"))},
                "quantitativeReference": {"referenceToReferenceProcess": id_by_process.get(_ref_id(ref_process))},
            },
            "modellingAndValidation": {"complianceDeclarations": []},
            "administrativeInformation": {**admin, "referenceToCommissioner": _empty_ref("contact"), "intendedApplications": [], "referenceToPersonOrEntityGeneratingTheDataSet": _empty_ref("contact"), "copyright": False, "licenseType": ""},
            "processInstances": [{"dataSetInternalID": i + 1, "referenceToProcess": _prism_ref(ref, "process"), "multiplicationFactor": 1.0} for i, ref in enumerate(process_refs)],
            "connections": connections,
        }
    raise AssertionError(kind)


def _apply_catalog_decisions(rows: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> None:
    by_id = {item.get("id"): item for item in catalog if isinstance(item, dict)}
    by_name = {
        (str(item.get("type")), str(item.get("name", "")).strip().casefold()): item
        for item in catalog
        if isinstance(item, dict)
    }
    for row in rows:
        exact = by_id.get(row["id"])
        named = by_name.get((row["type"], row["name"].strip().casefold()))
        if exact:
            row.update(decision="update", candidate_dataset_id=exact["id"], match_confidence=1.0, match_reason="same dataset UUID")
        elif named:
            row.update(decision="review", candidate_dataset_id=named["id"], match_confidence=0.9, match_reason="same normalized type and name")


def _warn_unresolved_import_references(rows: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    available = {row["id"] for row in rows}
    for row in rows:
        for path, target in _prism_references(row):
            if target and target not in available:
                warnings.append(_warning("UNRESOLVED_DATASET_REFERENCE", f"'{row['name']}' references a dataset outside this package.", dataset_id=row["id"], reference_id=target, path=path))


def _prism_references(row: dict[str, Any]) -> Iterable[tuple[str, str | None]]:
    payload = row["payload"]
    if row["type"] == "process":
        for i, item in enumerate(payload.get("exchanges", [])):
            yield f"exchanges[{i}].referenceToFlowDataSet", _ref_id(item.get("referenceToFlowDataSet"))
    elif row["type"] == "flow":
        for i, item in enumerate(payload.get("flowProperties", [])):
            yield f"flowProperties[{i}].referenceToFlowPropertyDataSet", _ref_id(item.get("referenceToFlowPropertyDataSet"))
    elif row["type"] == "flow_property":
        ref = _dig(payload, "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup")
        yield "flowPropertiesInformation.quantitativeReference.referenceToReferenceUnitGroup", _ref_id(ref)
    elif row["type"] == "model":
        for i, item in enumerate(payload.get("processInstances", [])):
            yield f"processInstances[{i}].referenceToProcess", _ref_id(item.get("referenceToProcess"))


def _flow_amount_refs(flow: dict[str, Any] | None, by_id: dict[str, dict[str, Any]]) -> tuple[dict | None, dict | None]:
    if not flow:
        return None, None
    factors = flow["payload"].get("flowProperties", [])
    reference_id = _dig(flow["payload"], "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty")
    factor = next((item for item in factors if item.get("dataSetInternalID") == reference_id), factors[0] if factors else None)
    if not factor:
        return None, None
    fp_ref = factor.get("referenceToFlowPropertyDataSet")
    fp = by_id.get(fp_ref.get("refObjectId")) if isinstance(fp_ref, dict) else None
    group_ref = _dig(fp["payload"], "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup") if fp else None
    group = by_id.get(group_ref.get("refObjectId")) if isinstance(group_ref, dict) else None
    unit_ref = None
    if group:
        units = group["payload"].get("units", [])
        ref_id = _dig(group["payload"], "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit")
        unit = next((item for item in units if item.get("dataSetInternalID") == ref_id), units[0] if units else None)
        if unit:
            unit_ref = {"@type": "Unit", "@id": _unit_id(group["id"], unit.get("dataSetInternalID", 1)), "name": unit.get("name") or "unit"}
    return _ref(fp_ref, "FlowProperty", by_id), unit_ref


def _linked_flow(provider: dict[str, Any] | None, consumer: dict[str, Any] | None) -> tuple[dict | None, int | None]:
    output = _reference_exchange(provider)
    if not output:
        return None, None
    flow_ref = output.get("referenceToFlowDataSet")
    target_id = _ref_id(flow_ref)
    for exchange in (consumer or {}).get("payload", {}).get("exchanges", []):
        if exchange.get("exchangeDirection") == "Input" and _ref_id(exchange.get("referenceToFlowDataSet")) == target_id:
            return flow_ref, exchange.get("dataSetInternalID")
    return flow_ref, None


def _reference_exchange(process: dict[str, Any] | None) -> dict[str, Any] | None:
    if not process:
        return None
    payload = process["payload"]
    reference_id = _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    return next((item for item in payload.get("exchanges", []) if item.get("dataSetInternalID") == reference_id), None)


def _ref(value: Any, olca_type: str, by_id: dict[str, dict[str, Any]]) -> dict | None:
    uid = _ref_id(value)
    if not uid:
        return None
    target = by_id.get(uid)
    name = value.get("shortDescription") if isinstance(value, dict) else None
    return _without_none({"@type": olca_type, "@id": uid, "name": (target or {}).get("name") or name})


def _prism_ref(value: Any, kind: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _empty_ref(kind)
    return {"type": kind, "refObjectId": value.get("@id"), "shortDescription": value.get("name") or ""}


def _empty_ref(kind: str) -> dict[str, Any]:
    return {"type": kind, "refObjectId": None, "shortDescription": ""}


def _import_admin(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "referenceToOwnershipOfDataSet": _empty_ref("contact"),
        "dataSetVersion": entity.get("version") or "01.01.000",
        "permanentDataSetURI": "",
        "timeStamp": entity.get("lastChange") or "",
    }


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    normalized = posixpath.normpath(name)
    mode = info.external_attr >> 16
    if name.startswith(("/", "\\")) or normalized == ".." or normalized.startswith("../") or "\\" in name:
        raise InterchangeError("UNSAFE_ARCHIVE_PATH", f"Unsafe ZIP entry '{name}'.", details={"path": name}, status_code=400)
    if stat.S_ISLNK(mode):
        raise InterchangeError("ARCHIVE_SYMLINK", f"ZIP entry '{name}' is a symbolic link.", details={"path": name}, status_code=400)


def _read_json_member(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InterchangeError("INVALID_OPENLCA_JSON", f"'{name}' is not valid UTF-8 JSON.", details={"path": name}, status_code=400) from exc
    if not isinstance(value, dict):
        raise InterchangeError("INVALID_OPENLCA_JSON", f"'{name}' must contain a JSON object.", details={"path": name}, status_code=400)
    return value


def _write_zip(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])
    return output.getvalue()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _entity_hash(entity: dict[str, Any]) -> str:
    value = copy.deepcopy(entity)
    other = value.get("otherProperties")
    if isinstance(other, dict):
        other.pop(_PRISM_EXTENSION, None)
        if not other:
            value.pop("otherProperties", None)
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _unit_id(group_id: str, internal_id: Any) -> str:
    return str(uuid.uuid5(_UNIT_NAMESPACE, f"{group_id}:{internal_id}"))


def _classification(payload: dict[str, Any], kind: str) -> list[str]:
    roots = {"model": "modelInformation", "process": "processInformation", "flow": "flowInformation", "flow_property": "flowPropertiesInformation", "unit_group": "unitGroupInformation"}
    root = roots.get(kind)
    if root:
        value = _dig(payload, root, "dataSetInformation", "classification")
    elif kind == "source":
        value = _dig(payload, "sourceInformation", "dataSetInformation", "classification")
    elif kind == "contact":
        value = _dig(payload, "contactInformation", "dataSetInformation", "classification")
    else:
        value = []
    return [str(item) for item in value] if isinstance(value, list) else []


def _flow_type(value: Any) -> str:
    return {"Elementary flow": "ELEMENTARY_FLOW", "Waste flow": "WASTE_FLOW"}.get(value, "PRODUCT_FLOW")


def _prism_flow_type(value: Any) -> str:
    return {"ELEMENTARY_FLOW": "Elementary flow", "WASTE_FLOW": "Waste flow", "PRODUCT_FLOW": "Product flow"}.get(value, "Other flow")


def _openlca_version(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "1.0.0"
    parts = value.split(".")
    try:
        return ".".join(str(int(part)) for part in parts)
    except ValueError:
        return value


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    for language in ("en", "zh"):
        for item in value:
            if isinstance(item, dict) and item.get("lang") == language and isinstance(item.get("text"), str):
                return item["text"]
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
    return ""


def _lang(value: Any) -> list[dict[str, str]]:
    return [{"lang": "en", "text": str(value)}] if value else []


def _number(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return default


def _dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _ref_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    result = value.get("@id", value.get("refObjectId"))
    return result if isinstance(result, str) and result else None


def _split_category(value: Any) -> list[str]:
    return [part for part in str(value).split("/") if part] if value else []


def _without_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}
