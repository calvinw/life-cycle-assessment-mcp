"""EcoSpold2 activity datasets ↔ PRISM workspace conversion.

The implementation follows the ecoinvent EcoSpold2 2.0.13 activity schema.
EcoSpold2 has no product-system document, so process links are represented by
``intermediateExchange.activityLinkId`` and an imported PRISM Model is
reconstructed from those links.
"""

from __future__ import annotations

import math
import re
import uuid
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

from .archive import MAX_PACKAGE_BYTES, open_safe_zip, write_deterministic_zip
from .bundle import prepare_export_bundle
from .errors import InterchangeError

ES = "http://www.EcoInvent.org/EcoSpold02"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NS = uuid.UUID("d39e6c64-8b56-4f5d-8d96-174b59eb16c1")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)

ET.register_namespace("", ES)


def export_ecospold2(bundle: dict[str, Any], model_id: str | None = None) -> bytes:
    """Export the selected PRISM Model closure as EcoSpold2 ``.spold`` files."""
    prepared = prepare_export_bundle(bundle, model_id)
    records = [row for values in prepared.values() for row in values]
    by_id = {row["id"]: row for row in records}
    processes = prepared["processes"]
    if not processes:
        raise InterchangeError(
            "ECOSPOLD2_NO_PROCESSES",
            "EcoSpold2 export requires at least one Process.",
        )

    providers_by_flow: dict[str, set[str]] = {}
    for process in processes:
        reference_flow = _reference_flow_id(process)
        if reference_flow:
            providers_by_flow.setdefault(reference_flow, set()).add(process["id"])
    provider_by_exchange = _model_providers(prepared["models"], by_id)

    entries: dict[str, bytes] = {}
    for process in sorted(processes, key=lambda row: row["id"]):
        root = ET.Element(_q("ecoSpold"))
        root.append(
            _activity_dataset(
                process,
                by_id,
                providers_by_flow,
                provider_by_exchange,
            )
        )
        entries[f"datasets/{process['id']}.spold"] = ET.tostring(
            root, encoding="utf-8", xml_declaration=True, short_empty_elements=True
        )
    return write_deterministic_zip(entries)


def preview_ecospold2(package: bytes) -> dict[str, Any]:
    """Import a raw EcoSpold2 XML file or ZIP containing ``.spold`` files."""
    documents, warnings = _read_documents(package)
    activities: list[tuple[ET.Element, str]] = []
    seen: set[str] = set()
    for root, path in documents:
        if _local(root.tag) != "ecoSpold" or _namespace(root.tag) != ES:
            raise InterchangeError(
                "INVALID_ECOSPOLD2_ROOT",
                f"'{path}' is not an EcoSpold2 document.",
                details={"path": path},
            )
        for dataset in _children(root, "activityDataset"):
            activity = _child(_child(dataset, "activityDescription"), "activity")
            activity_id = activity.get("id") if activity is not None else None
            if not _is_uuid(activity_id):
                raise InterchangeError(
                    "INVALID_ECOSPOLD2_ACTIVITY_ID",
                    f"'{path}' contains an Activity without a valid UUID.",
                    details={"path": path, "activity_id": activity_id},
                )
            if activity_id in seen:
                raise InterchangeError(
                    "DUPLICATE_ECOSPOLD2_ACTIVITY",
                    f"Activity '{activity_id}' occurs more than once.",
                    details={"activity_id": activity_id},
                )
            seen.add(activity_id)
            activities.append((dataset, path))
        if _children(root, "childActivityDataset"):
            warnings.append(_warning(
                "UNSUPPORTED_ECOSPOLD2_CHILD_ACTIVITY",
                f"Ignored inherited child Activity datasets in '{path}'.",
                path=path,
            ))
    if not activities:
        raise InterchangeError(
            "EMPTY_ECOSPOLD2_PACKAGE",
            "The package contains no EcoSpold2 Activity datasets.",
        )

    unit_specs: dict[tuple[str, str], tuple[str, str]] = {}
    flow_specs: dict[tuple[str, str], dict[str, Any]] = {}
    process_rows: list[dict[str, Any]] = []
    links: list[tuple[str, str]] = []

    for dataset, path in activities:
        process, process_links = _process_from_activity(
            dataset, path, unit_specs, flow_specs, warnings
        )
        process_rows.append(process)
        links.extend((provider, process["id"]) for provider in process_links)

    known_processes = {row["id"] for row in process_rows}
    connections = sorted({link for link in links if link[0] in known_processes})
    for provider, consumer in sorted(set(links) - set(connections)):
        warnings.append(_warning(
            "UNRESOLVED_ECOSPOLD2_ACTIVITY_LINK",
            f"Process '{consumer}' references Activity '{provider}', which is not in the package.",
            activity_id=consumer,
            provider_activity_id=provider,
        ))

    unit_groups, flow_properties, unit_refs = _reference_rows(unit_specs)
    flow_ids = [spec["id"] for spec in flow_specs.values()]
    if len(flow_ids) != len(set(flow_ids)):
        raise InterchangeError(
            "ECOSPOLD2_FLOW_TYPE_CONFLICT",
            "The same EcoSpold2 master-data UUID is used for both an intermediate and elementary exchange.",
        )
    flows = [
        _flow_row(spec, unit_refs[spec["unit_key"]])
        for _, spec in sorted(flow_specs.items())
    ]
    model = _model_row(process_rows, connections)
    datasets = [model, *process_rows, *flows, *flow_properties, *unit_groups]
    datasets.sort(key=lambda row: (row["type"], row["name"].casefold(), row["id"]))
    summary = {
        "model": 1,
        "process": len(process_rows),
        "flow": len(flows),
        "flow_property": len(flow_properties),
        "unit_group": len(unit_groups),
        "source": 0,
        "contact": 0,
    }
    warnings.append(_warning(
        "ECOSPOLD2_MODEL_RECONSTRUCTED",
        "EcoSpold2 has no product-system layer; one PRISM Model was reconstructed from activityLinkId references.",
    ))
    return {
        "format": "ecospold2",
        "valid": True,
        "summary": summary,
        "datasets": datasets,
        "matches": [],
        "warnings": warnings,
        "errors": [],
    }


def looks_like_ecospold2_xml(package: bytes) -> bool:
    head = package[:4096].lstrip()
    return head.startswith(b"<?xml") or head.startswith(b"<ecoSpold")


def is_ecospold2_zip(package: bytes, names: set[str]) -> bool:
    candidates = [name for name in names if name.lower().endswith((".spold", ".xml"))]
    if not candidates:
        return False
    try:
        archive = open_safe_zip(package)
        with archive:
            for name in sorted(candidates):
                with archive.open(name) as stream:
                    raw = stream.read(4096)
                if b"EcoSpold02" in raw and b"ecoSpold" in raw:
                    return True
    except Exception:
        return False
    return False


def _activity_dataset(
    process: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    providers_by_flow: dict[str, set[str]],
    provider_by_exchange: dict[tuple[str, str], str],
) -> ET.Element:
    payload = process["payload"]
    dataset = ET.Element(_q("activityDataset"))
    description = _sub(dataset, "activityDescription")
    activity = _sub(
        description,
        "activity",
        id=process["id"],
        activityNameId=_uid("activity-name", process["id"]),
        type=1,
        specialActivityType=0,
    )
    _lang(activity, "activityName", process["name"])
    comment = process.get("description") or _first_text(
        _dig(payload, "processInformation", "dataSetInformation", "generalComment")
    )
    if comment:
        _text_and_image(activity, "generalComment", comment)

    location = _dig(payload, "processInformation", "geography", "location") or "GLO"
    geography = _sub(description, "geography", geographyId=_uid("geography", location))
    _lang(geography, "shortname", location)
    _sub(description, "technology", technologyLevel=3)
    year = _year(_dig(payload, "processInformation", "time", "referenceYear"))
    _sub(
        description,
        "timePeriod",
        startDate=f"{year:04d}-01-01",
        endDate=f"{year:04d}-12-31",
        isDataValidForEntirePeriod="true",
    )
    scenario = _sub(
        description,
        "macroEconomicScenario",
        macroEconomicScenarioId=_uid("scenario", "business-as-usual"),
    )
    _lang(scenario, "name", "Business-as-Usual")

    flow_data = _sub(dataset, "flowData")
    reference_internal_id = _dig(
        payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow"
    )
    for index, exchange in enumerate(_dicts(payload.get("exchanges")), start=1):
        reference = exchange.get("referenceToFlowDataSet")
        flow_id = _ref_id(reference)
        flow = by_id.get(flow_id or "")
        if flow is None or flow.get("type") != "flow":
            raise InterchangeError(
                "UNRESOLVED_DATASET_REFERENCE",
                f"Process '{process['id']}' has an unresolved Flow reference.",
                details={"process_id": process["id"], "flow_id": flow_id},
            )
        unit_id, unit_name = _flow_unit(flow, by_id)
        is_input = exchange.get("exchangeDirection") == "Input"
        amount = _finite(exchange.get("meanAmount"), "exchange.meanAmount")
        common = {
            "id": _uid("exchange", process["id"], str(exchange.get("dataSetInternalID", index))),
            "unitId": unit_id,
            "amount": amount,
        }
        flow_type = _dig(flow["payload"], "modellingAndValidation", "typeOfDataSet")
        if flow_type == "Elementary flow":
            item = _sub(
                flow_data,
                "elementaryExchange",
                elementaryExchangeId=flow["id"],
                **common,
            )
            _lang(item, "name", flow["name"])
            _lang(item, "unitName", unit_name)
            compartment_name, subcompartment_name = _compartment(flow)
            compartment = _sub(
                item,
                "compartment",
                subcompartmentId=_uid("subcompartment", compartment_name, subcompartment_name),
            )
            _lang(compartment, "compartment", compartment_name)
            _lang(compartment, "subcompartment", subcompartment_name)
            _sub(item, "inputGroup" if is_input else "outputGroup", text="4")
        else:
            provider = provider_by_exchange.get((process["id"], flow["id"]))
            if provider is None:
                candidates = providers_by_flow.get(flow["id"], set()) - {process["id"]}
                if len(candidates) == 1:
                    provider = next(iter(candidates))
            attrs = {"intermediateExchangeId": flow["id"], **common}
            if is_input and provider and provider != process["id"]:
                attrs["activityLinkId"] = provider
            item = _sub(flow_data, "intermediateExchange", **attrs)
            _lang(item, "name", flow["name"])
            _lang(item, "unitName", unit_name)
            if is_input:
                _sub(item, "inputGroup", text="5")
            else:
                is_reference = exchange.get("dataSetInternalID", index) == reference_internal_id
                _sub(item, "outputGroup", text="0" if is_reference else "2")

    _sub(dataset, "modellingAndValidation")
    admin = _sub(dataset, "administrativeInformation")
    person_id = _uid("person", "prism-interchange")
    person = {
        "personId": person_id,
        "personName": "PRISM LCA",
        "personEmail": "noreply@lca-mcp.mathplosion.com",
    }
    _sub(admin, "dataEntryBy", **person)
    _sub(
        admin,
        "dataGeneratorAndPublication",
        **person,
        dataPublishedIn=0,
        isCopyrightProtected="false",
        accessRestrictedTo=0,
    )
    major_release, minor_release, major_revision, minor_revision = _version(payload)
    _sub(
        admin,
        "fileAttributes",
        majorRelease=major_release,
        minorRelease=minor_release,
        majorRevision=major_revision,
        minorRevision=minor_revision,
        defaultLanguage="en",
        fileGenerator="PRISM LCA interchange",
        fileTimestamp=_timestamp(payload),
    )
    return dataset


def _process_from_activity(
    dataset: ET.Element,
    path: str,
    unit_specs: dict[tuple[str, str], tuple[str, str]],
    flow_specs: dict[tuple[str, str], dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    description = _child(dataset, "activityDescription")
    activity = _child(description, "activity")
    process_id = activity.get("id")
    name = _text(_child(activity, "activityName")) or f"Activity {process_id}"
    general_comment = _text(_find(activity, "generalComment", "text"))
    geography = _child(description, "geography")
    location = _text(_child(geography, "shortname")) or "GLO"
    time_period = _child(description, "timePeriod")
    reference_year = _date_year(time_period.get("startDate") if time_period is not None else None)
    file_attributes = _find(dataset, "administrativeInformation", "fileAttributes")
    version = _version_string(file_attributes)
    timestamp = file_attributes.get("fileTimestamp") if file_attributes is not None else None
    unsupported = sorted(
        {
            _local(element.tag)
            for element in dataset.iter()
            if _local(element.tag)
            in {
                "allocation",
                "classification",
                "impactIndicator",
                "parameter",
                "pedigreeMatrix",
                "property",
                "representativeness",
                "review",
                "transferCoefficient",
                "uncertainty",
            }
        }
    )
    if unsupported:
        warnings.append(_warning(
            "UNSUPPORTED_ECOSPOLD2_FIELDS",
            f"Activity '{name}' contains EcoSpold2 fields that PRISM cannot represent and did not import.",
            activity_id=process_id,
            fields=unsupported,
        ))

    exchanges: list[dict[str, Any]] = []
    reference_internal_id: int | None = None
    providers: list[str] = []
    flow_data = _child(dataset, "flowData")
    all_exchanges = [] if flow_data is None else list(flow_data)
    for index, item in enumerate(all_exchanges, start=1):
        kind = _local(item.tag)
        if kind not in {"intermediateExchange", "elementaryExchange"}:
            if kind not in {"parameter", "impactIndicator"}:
                warnings.append(_warning(
                    "UNSUPPORTED_ECOSPOLD2_FLOW_ENTRY",
                    f"Ignored unsupported flowData entry '{kind}'.",
                    path=path,
                ))
            continue
        flow_id = item.get(
            "intermediateExchangeId" if kind == "intermediateExchange" else "elementaryExchangeId"
        )
        if not _is_uuid(flow_id):
            raise InterchangeError(
                "INVALID_ECOSPOLD2_FLOW_ID",
                f"'{path}' contains an exchange without a valid master-data UUID.",
                details={"path": path, "flow_id": flow_id},
            )
        flow_name = _text(_child(item, "name")) or f"Flow {flow_id}"
        unit_id = item.get("unitId") or _uid("unit", _text(_child(item, "unitName")) or "unit")
        unit_name = _text(_child(item, "unitName")) or "unit"
        unit_key = (unit_id, unit_name)
        unit_specs[unit_key] = (unit_id, unit_name)
        flow_key = (kind, flow_id)
        specification = {
                "id": flow_id,
                "name": flow_name,
                "description": None,
                "elementary": kind == "elementaryExchange",
                "unit_key": unit_key,
                "compartment": _text(_find(item, "compartment", "compartment")),
                "subcompartment": _text(_find(item, "compartment", "subcompartment")),
            }
        previous = flow_specs.setdefault(flow_key, specification)
        if previous["unit_key"] != unit_key:
            raise InterchangeError(
                "INCONSISTENT_ECOSPOLD2_FLOW_UNIT",
                f"Flow '{flow_id}' is used with more than one unit.",
                details={"flow_id": flow_id},
            )
        input_group = _child(item, "inputGroup")
        output_group = _child(item, "outputGroup")
        direction = "Input" if input_group is not None else "Output"
        amount = _finite(item.get("amount"), f"{path}.exchange[{index}].amount")
        exchanges.append(
            {
                "dataSetInternalID": index,
                "referenceToFlowDataSet": {
                    "type": "flow",
                    "refObjectId": flow_id,
                    "shortDescription": flow_name,
                },
                "exchangeDirection": direction,
                "meanAmount": amount,
                "resultingAmount": amount,
                "generalComment": _lang_value(_children(item, "comment")),
            }
        )
        if output_group is not None and _text(output_group) == "0":
            reference_internal_id = index
        provider = item.get("activityLinkId")
        if direction == "Input" and _is_uuid(provider):
            providers.append(provider)

    if reference_internal_id is None:
        reference_internal_id = next(
            (row["dataSetInternalID"] for row in exchanges if row["exchangeDirection"] == "Output"),
            None,
        )
        warnings.append(_warning(
            "ECOSPOLD2_REFERENCE_OUTPUT_INFERRED",
            f"Activity '{name}' has no outputGroup 0; its first output was used as the quantitative reference.",
            activity_id=process_id,
        ))
    if reference_internal_id is None:
        raise InterchangeError(
            "ECOSPOLD2_MISSING_REFERENCE_OUTPUT",
            f"Activity '{name}' has no output exchange.",
            details={"activity_id": process_id},
        )

    row = _row(
        process_id,
        "process",
        name,
        general_comment,
        {
            "processInformation": {
                "dataSetInformation": {
                    "name": {"baseName": [{"lang": "en", "text": name}], "treatmentStandardsRoutes": [], "mixAndLocationTypes": []},
                    "classification": [],
                    "generalComment": _lang_value_text(general_comment),
                },
                "quantitativeReference": {"referenceToReferenceFlow": reference_internal_id},
                "time": {"referenceYear": reference_year} if reference_year else {},
                "geography": {"location": location},
            },
            "modellingAndValidation": {"typeOfDataSet": "Unit process, single operation"},
            "administrativeInformation": {
                "dataSetVersion": version,
                **({"timeStamp": timestamp} if timestamp else {}),
            },
            "exchanges": exchanges,
        },
    )
    return row, providers


def _reference_rows(
    unit_specs: dict[tuple[str, str], tuple[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str], tuple[str, str]]]:
    unit_groups: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    refs: dict[tuple[str, str], tuple[str, str]] = {}
    for key, (source_unit_id, name) in sorted(unit_specs.items()):
        unit_group_id = _uid("unit-group", source_unit_id, name)
        property_id = _uid("flow-property", source_unit_id, name)
        refs[key] = (property_id, unit_group_id)
        unit_groups.append(_row(
            unit_group_id,
            "unit_group",
            f"Units of {name}",
            f"Reconstructed from EcoSpold2 unit '{name}'.",
            {
                "unitGroupInformation": {
                    "dataSetInformation": {"name": [{"lang": "en", "text": f"Units of {name}"}], "classification": [], "generalComment": []},
                    "quantitativeReference": {"referenceToReferenceUnit": 1},
                },
                "units": [{"dataSetInternalID": 1, "name": name, "meanValue": 1.0, "generalComment": []}],
                "administrativeInformation": {"dataSetVersion": "01.00.000"},
            },
        ))
        properties.append(_row(
            property_id,
            "flow_property",
            name,
            f"Reconstructed from EcoSpold2 unit '{name}'.",
            {
                "flowPropertiesInformation": {
                    "dataSetInformation": {"name": [{"lang": "en", "text": name}], "classification": [], "generalComment": []},
                    "quantitativeReference": {"referenceToReferenceUnitGroup": {"type": "unit_group", "refObjectId": unit_group_id, "shortDescription": f"Units of {name}"}},
                },
                "administrativeInformation": {"dataSetVersion": "01.00.000"},
            },
        ))
    return unit_groups, properties, refs


def _flow_row(spec: dict[str, Any], refs: tuple[str, str]) -> dict[str, Any]:
    property_id, _ = refs
    name = spec["name"]
    comment = None
    if spec.get("elementary") and (spec.get("compartment") or spec.get("subcompartment")):
        comment = " / ".join(filter(None, [spec.get("compartment"), spec.get("subcompartment")]))
    return _row(
        spec["id"],
        "flow",
        name,
        comment,
        {
            "flowInformation": {
                "dataSetInformation": {
                    "name": {"baseName": [{"lang": "en", "text": name}], "treatmentStandardsRoutes": [], "mixAndLocationTypes": []},
                    "classification": [],
                    "generalComment": _lang_value_text(comment),
                },
                "quantitativeReference": {"referenceToReferenceFlowProperty": 1},
            },
            "modellingAndValidation": {"typeOfDataSet": "Elementary flow" if spec.get("elementary") else "Product flow"},
            "flowProperties": [{
                "dataSetInternalID": 1,
                "referenceToFlowPropertyDataSet": {"type": "flow_property", "refObjectId": property_id, "shortDescription": spec["unit_key"][1]},
                "meanValue": 1.0,
                "generalComment": [],
            }],
            "administrativeInformation": {"dataSetVersion": "01.00.000"},
        },
    )


def _model_row(processes: list[dict[str, Any]], connections: list[tuple[str, str]]) -> dict[str, Any]:
    ids = sorted(row["id"] for row in processes)
    model_id = _uid("model", *ids)
    instances = []
    internal_by_process = {process_id: index for index, process_id in enumerate(ids, start=1)}
    names = {row["id"]: row["name"] for row in processes}
    for process_id in ids:
        instances.append({
            "dataSetInternalID": internal_by_process[process_id],
            "referenceToProcess": {"type": "process", "refObjectId": process_id, "shortDescription": names[process_id]},
            "multiplicationFactor": 1.0,
        })
    providers = {source for source, _ in connections}
    consumers = {target for _, target in connections}
    sinks = sorted(consumers - providers) or ids
    reference_process = internal_by_process[sinks[-1]]
    name = f"EcoSpold2 import ({len(processes)} activities)"
    return _row(
        model_id,
        "model",
        name,
        "Reconstructed from EcoSpold2 activity links.",
        {
            "modelInformation": {
                "dataSetInformation": {"name": {"baseName": [{"lang": "en", "text": name}], "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": [], "generalComment": []},
                "quantitativeReference": {"referenceToReferenceProcess": reference_process},
            },
            "processInstances": instances,
            "connections": [
                {"fromInstanceId": internal_by_process[source], "toInstanceId": internal_by_process[target]}
                for source, target in connections
            ],
            "administrativeInformation": {"dataSetVersion": "01.00.000"},
        },
    )


def _read_documents(package: bytes) -> tuple[list[tuple[ET.Element, str]], list[dict[str, Any]]]:
    if len(package) > MAX_PACKAGE_BYTES:
        raise InterchangeError(
            "PACKAGE_TOO_LARGE",
            "The compressed package exceeds the 25 MB limit.",
            details={"compressed_bytes": len(package), "limit_bytes": MAX_PACKAGE_BYTES},
            status_code=413,
        )
    warnings: list[dict[str, Any]] = []
    if looks_like_ecospold2_xml(package):
        return [(_parse_xml(package, "upload.spold"), "upload.spold")], warnings
    archive = open_safe_zip(package)
    documents: list[tuple[ET.Element, str]] = []
    with archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith((".spold", ".xml")):
                continue
            raw = archive.read(info)
            try:
                root = _parse_xml(raw, info.filename)
            except InterchangeError:
                warnings.append(_warning(
                    "UNSUPPORTED_PACKAGE_ENTRY",
                    f"Ignored non-EcoSpold2 XML file '{info.filename}'.",
                    path=info.filename,
                ))
                continue
            if _local(root.tag) == "ecoSpold" and _namespace(root.tag) == ES:
                documents.append((root, info.filename))
    if not documents:
        raise InterchangeError(
            "EMPTY_ECOSPOLD2_PACKAGE",
            "The package contains no EcoSpold2 XML documents.",
        )
    return documents, warnings


def _parse_xml(raw: bytes, path: str) -> ET.Element:
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise InterchangeError(
            "INVALID_ECOSPOLD2_XML",
            f"'{path}' contains a forbidden XML entity declaration.",
            details={"path": path},
        )
    try:
        return ET.fromstring(raw)
    except (ET.ParseError, UnicodeError, ValueError) as exc:
        raise InterchangeError(
            "INVALID_ECOSPOLD2_XML",
            f"'{path}' is not valid EcoSpold2 XML.",
            details={"path": path},
        ) from exc


def _flow_unit(flow: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> tuple[str, str]:
    payload = flow["payload"]
    reference_id = _dig(payload, "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty")
    factors = _dicts(payload.get("flowProperties"))
    factor = next((item for item in factors if item.get("dataSetInternalID") == reference_id), factors[0] if factors else None)
    property_row = by_id.get(_ref_id(factor.get("referenceToFlowPropertyDataSet")) if factor else "")
    unit_group_ref = _dig(property_row or {}, "payload", "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup")
    unit_group = by_id.get(_ref_id(unit_group_ref) or "")
    units = _dicts(_dig(unit_group or {}, "payload", "units"))
    reference_unit = _dig(unit_group or {}, "payload", "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit")
    unit = next((item for item in units if item.get("dataSetInternalID") == reference_unit), units[0] if units else None)
    name = str(unit.get("name")) if unit and unit.get("name") else "unit"
    source = unit_group["id"] if unit_group else flow["id"]
    return _uid("unit", source, str(reference_unit), name), name


def _reference_flow_id(process: dict[str, Any]) -> str | None:
    payload = process["payload"]
    reference = _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    for exchange in _dicts(payload.get("exchanges")):
        if exchange.get("dataSetInternalID") == reference and exchange.get("exchangeDirection") == "Output":
            return _ref_id(exchange.get("referenceToFlowDataSet"))
    return None


def _model_providers(
    models: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], str]:
    """Map a consumer Process/Flow pair to the provider declared by a Model edge."""
    result: dict[tuple[str, str], str] = {}
    for model in models:
        instances = {
            item.get("dataSetInternalID"): _ref_id(item.get("referenceToProcess"))
            for item in _dicts(model["payload"].get("processInstances"))
        }
        for connection in _dicts(model["payload"].get("connections")):
            provider = instances.get(connection.get("fromInstanceId"))
            consumer = instances.get(connection.get("toInstanceId"))
            process = by_id.get(provider or "")
            flow_id = _reference_flow_id(process) if process else None
            if provider and consumer and flow_id:
                result[(consumer, flow_id)] = provider
    return result


def _compartment(flow: dict[str, Any]) -> tuple[str, str]:
    classifications = _dig(flow["payload"], "flowInformation", "dataSetInformation", "classification")
    values: list[str] = []
    if isinstance(classifications, list):
        values = [str(value) for value in classifications if value]
    if values:
        return values[0], values[1] if len(values) > 1 else "unspecified"
    name = flow["name"].casefold()
    if "water" in name:
        return "natural resource", "in water"
    return "air", "unspecified"


def _version(payload: dict[str, Any]) -> tuple[int, int, int, int]:
    raw = str(_dig(payload, "administrativeInformation", "dataSetVersion") or "01.00.001")
    parts = [int(value) for value in re.findall(r"\d+", raw)]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], max(parts[2], 1), 0


def _version_string(file_attributes: ET.Element | None) -> str:
    if file_attributes is None:
        return "01.00.001"
    return "{:02d}.{:02d}.{:03d}".format(
        _int(file_attributes.get("majorRelease"), 1),
        _int(file_attributes.get("minorRelease"), 0),
        _int(file_attributes.get("majorRevision"), 1),
    )


def _timestamp(payload: dict[str, Any]) -> str:
    value = _dig(payload, "administrativeInformation", "timeStamp")
    if isinstance(value, str) and value:
        return value
    return "1970-01-01T00:00:00Z"


def _row(row_id: str, kind: str, name: str, description: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "temporary_id": f"import:{kind}:{row_id}",
        "source_id": row_id,
        "id": row_id,
        "type": kind,
        "name": name,
        "description": description or "",
        "payload": payload,
        "decision": "create",
    }


def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if details:
        result["details"] = details
    return result


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: Any) -> ET.Element:
    item = ET.SubElement(parent, _q(tag))
    for key, value in attrs.items():
        if value is not None:
            item.set(key, str(value).lower() if isinstance(value, bool) else str(value))
    if text is not None:
        item.text = text
    return item


def _lang(parent: ET.Element, tag: str, text: str, lang: str = "en") -> ET.Element:
    item = _sub(parent, tag, text)
    item.set(XML_LANG, lang)
    return item


def _text_and_image(parent: ET.Element, tag: str, text: str) -> None:
    container = _sub(parent, tag)
    item = _lang(container, "text", text)
    item.set("index", "1")


def _q(tag: str) -> str:
    return f"{{{ES}}}{tag}"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _child(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    return next((item for item in parent if _local(item.tag) == name), None)


def _children(parent: ET.Element | None, name: str) -> list[ET.Element]:
    return [] if parent is None else [item for item in parent if _local(item.tag) == name]


def _find(parent: ET.Element | None, *path: str) -> ET.Element | None:
    for name in path:
        parent = _child(parent, name)
        if parent is None:
            return None
    return parent


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _lang_value(elements: list[ET.Element]) -> list[dict[str, str]]:
    return [
        {"lang": item.get(XML_LANG, "en"), "text": _text(item)}
        for item in elements
        if _text(item)
    ]


def _lang_value_text(value: str | None) -> list[dict[str, str]]:
    return [{"lang": "en", "text": value}] if value else []


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"]:
                return item["text"]
    return None


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _ref_id(value: Any) -> str | None:
    result = value.get("refObjectId") if isinstance(value, dict) else None
    return result if isinstance(result, str) and result else None


def _uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "|".join(parts)))


def _is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _finite(value: Any, path: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InterchangeError("INVALID_ECOSPOLD2_NUMBER", f"'{path}' must be a number.") from exc
    if not math.isfinite(number):
        raise InterchangeError("INVALID_ECOSPOLD2_NUMBER", f"'{path}' must be finite.")
    return number


def _year(value: Any) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return 2000
    return year if 1 <= year <= 9999 else 2000


def _date_year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value[:4])
    except (TypeError, ValueError):
        return None


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
