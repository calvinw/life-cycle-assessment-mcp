"""Shared validation and selection for PRISM interchange exports."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from collections import deque
from typing import Any

from .errors import InterchangeError

PLURAL_KEYS = {
    "model": "models",
    "process": "processes",
    "flow": "flows",
    "flow_property": "flow_properties",
    "unit_group": "unit_groups",
    "source": "sources",
    "contact": "contacts",
}
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def prepare_export_bundle(
    bundle: dict[str, Any], model_id: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Normalize, optionally select a Model closure, and validate a bundle."""
    records = read_bundle(bundle)
    if model_id is not None:
        records = select_model_closure(records, model_id)
    validate_references(records)
    grouped = {plural: [] for plural in PLURAL_KEYS.values()}
    for row in sorted(records, key=lambda item: (item["type"], item["id"])):
        grouped[PLURAL_KEYS[row["type"]]].append(row)
    return grouped


def read_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict):
        raise InterchangeError(
            "MALFORMED_BUNDLE", "The export bundle must be a JSON object.", status_code=400
        )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, plural in PLURAL_KEYS.items():
        values = bundle.get(plural, [])
        if not isinstance(values, list):
            raise InterchangeError(
                "MALFORMED_BUNDLE", f"'{plural}' must be an array.",
                details={"field": plural}, status_code=400,
            )
        for index, raw in enumerate(values):
            if not isinstance(raw, dict):
                raise InterchangeError(
                    "MALFORMED_DATASET", f"{plural}[{index}] must be an object.",
                    status_code=400,
                )
            row = copy.deepcopy(raw)
            row_id = row.get("id")
            if not isinstance(row_id, str) or not _UUID_RE.match(row_id):
                raise InterchangeError(
                    "INVALID_DATASET_ID", f"{plural}[{index}] must have a UUID id.",
                    details={"field": f"{plural}[{index}].id"},
                )
            if row_id in seen:
                raise InterchangeError(
                    "DUPLICATE_DATASET_ID", f"Dataset id '{row_id}' occurs more than once.",
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
                    "MISSING_DATASET_NAME", f"Dataset '{row_id}' must have a name.",
                    details={"dataset_id": row_id},
                )
            if not isinstance(row.get("payload", {}), dict):
                raise InterchangeError(
                    "INVALID_DATASET_PAYLOAD", f"Dataset '{row_id}' payload must be an object.",
                    details={"dataset_id": row_id},
                )
            row["type"] = kind
            row.setdefault("description", None)
            row.setdefault("payload", {})
            records.append(row)
    if not records:
        raise InterchangeError("EMPTY_BUNDLE", "The export bundle contains no datasets.")
    return records


def select_model_closure(
    records: list[dict[str, Any]], model_id: str
) -> list[dict[str, Any]]:
    """Return the transitive dataset closure for one Model."""
    by_id = {row["id"]: row for row in records}
    model = by_id.get(model_id)
    if model is None or model["type"] != "model":
        raise InterchangeError(
            "UNKNOWN_EXPORT_MODEL", f"Model '{model_id}' is not present in the export bundle.",
            details={"model_id": model_id},
        )
    selected: dict[str, dict[str, Any]] = {}
    pending = deque([model])
    while pending:
        row = pending.popleft()
        if row["id"] in selected:
            continue
        selected[row["id"]] = row
        for expected_type, target_id, path, required in _references(row):
            if not target_id:
                if required:
                    raise _unresolved(row["id"], expected_type, target_id, path)
                continue
            target = by_id.get(target_id)
            if target is None or target["type"] != expected_type:
                raise _unresolved(row["id"], expected_type, target_id, path)
            pending.append(target)
    return list(selected.values())


def validate_references(records: list[dict[str, Any]]) -> None:
    by_id = {row["id"]: row for row in records}
    for row in records:
        for expected_type, target_id, path, required in _references(row):
            if not target_id:
                if required:
                    raise _unresolved(row["id"], expected_type, target_id, path)
                continue
            target = by_id.get(target_id)
            if target is None or target["type"] != expected_type:
                raise _unresolved(row["id"], expected_type, target_id, path)
        _validate_internal_ids(row)


def _references(row: dict[str, Any]) -> Iterable[tuple[str, str | None, str, bool]]:
    payload = row["payload"]
    kind = row["type"]
    if kind == "model":
        for index, instance in enumerate(_dicts(payload.get("processInstances"))):
            yield "process", _ref_id(instance.get("referenceToProcess")), f"processInstances[{index}].referenceToProcess", True
    elif kind == "process":
        for index, exchange in enumerate(_dicts(payload.get("exchanges"))):
            yield "flow", _ref_id(exchange.get("referenceToFlowDataSet")), f"exchanges[{index}].referenceToFlowDataSet", True
        modelling = payload.get("modellingAndValidation")
        if isinstance(modelling, dict):
            yield "source", _ref_id(modelling.get("referenceToDataSource")), "modellingAndValidation.referenceToDataSource", False
        admin = payload.get("administrativeInformation")
        if isinstance(admin, dict):
            for field in ("referenceToOwnershipOfDataSet", "referenceToCommissioner", "referenceToPersonOrEntityGeneratingTheDataSet"):
                yield "contact", _ref_id(admin.get(field)), f"administrativeInformation.{field}", False
    elif kind == "flow":
        for index, factor in enumerate(_dicts(payload.get("flowProperties"))):
            yield "flow_property", _ref_id(factor.get("referenceToFlowPropertyDataSet")), f"flowProperties[{index}].referenceToFlowPropertyDataSet", True
    elif kind == "flow_property":
        yield "unit_group", _ref_id(_dig(payload, "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup")), "flowPropertiesInformation.quantitativeReference.referenceToReferenceUnitGroup", True
        modelling = payload.get("modellingAndValidation")
        if isinstance(modelling, dict):
            yield "source", _ref_id(modelling.get("referenceToDataSource")), "modellingAndValidation.referenceToDataSource", False
    elif kind == "source":
        yield "contact", _ref_id(_dig(payload, "sourceInformation", "dataSetInformation", "referenceToContact")), "sourceInformation.dataSetInformation.referenceToContact", False


def _validate_internal_ids(row: dict[str, Any]) -> None:
    payload = row["payload"]
    kind = row["type"]
    if kind == "model":
        ids = _ids(row, "processInstances")
        _require_member(row, _dig(payload, "modelInformation", "quantitativeReference", "referenceToReferenceProcess"), ids, "referenceToReferenceProcess")
        known = set(ids)
        for index, connection in enumerate(_dicts(payload.get("connections"))):
            for field in ("fromInstanceId", "toInstanceId"):
                if connection.get(field) not in known:
                    raise InterchangeError(
                        "INVALID_INTERNAL_REFERENCE", f"Model '{row['id']}' has a connection to an unknown Process instance.",
                        details={"dataset_id": row["id"], "path": f"connections[{index}].{field}", "internal_id": connection.get(field)},
                    )
    elif kind == "process":
        ids = _ids(row, "exchanges")
        _require_member(row, _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow"), ids, "referenceToReferenceFlow")
    elif kind == "flow":
        ids = _ids(row, "flowProperties")
        _require_member(row, _dig(payload, "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty"), ids, "referenceToReferenceFlowProperty")
    elif kind == "unit_group":
        ids = _ids(row, "units")
        _require_member(row, _dig(payload, "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit"), ids, "referenceToReferenceUnit")


def _ids(row: dict[str, Any], field: str) -> list[Any]:
    ids = [item.get("dataSetInternalID") for item in _dicts(row["payload"].get(field))]
    if any(value is None or isinstance(value, bool) for value in ids) or len(ids) != len(set(ids)):
        raise InterchangeError(
            "INVALID_INTERNAL_ID", f"Dataset '{row['id']}' has missing or duplicate internal IDs in '{field}'.",
            details={"dataset_id": row["id"], "path": field, "internal_ids": ids},
        )
    return ids


def _require_member(row: dict[str, Any], reference: Any, ids: list[Any], field: str) -> None:
    if reference is not None and reference not in ids:
        raise InterchangeError(
            "INVALID_INTERNAL_REFERENCE", f"Dataset '{row['id']}' has an unresolved quantitative reference.",
            details={"dataset_id": row["id"], "path": field, "internal_id": reference},
        )


def _unresolved(owner: str, expected: str, target_id: Any, path: str) -> InterchangeError:
    return InterchangeError(
        "UNRESOLVED_DATASET_REFERENCE", f"Dataset '{owner}' has an unresolved {expected} reference.",
        details={"dataset_id": owner, "reference_id": target_id, "path": path},
    )


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
