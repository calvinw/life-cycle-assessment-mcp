"""SimaPro process CSV ↔ PRISM workspace conversion.

This module implements the process-inventory subset of SimaPro CSV.  The
format has no product-system object, so a PRISM Model is reconstructed from
technosphere product-name links on import.
"""

from __future__ import annotations

import ast
import csv
import io
import math
import re
import uuid
from typing import Any

from .archive import MAX_PACKAGE_BYTES
from .bundle import prepare_export_bundle
from .errors import InterchangeError

NS = uuid.UUID("31ed85ac-88c0-4a19-b428-a9c46c19381a")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_FLOW_ID_RE = re.compile(
    r"(?:PRISM-FLOW-ID|PRISM flow UUID)\s*:\s*"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})",
    re.IGNORECASE,
)

_SECTIONS = {
    "Products", "Avoided products", "Resources", "Materials/fuels",
    "Electricity/heat", "Emissions to air", "Emissions to water",
    "Emissions to soil", "Final waste flows", "Non material emissions",
    "Social issues", "Economic issues", "Waste to treatment",
    "Input parameters", "Calculated parameters", "Waste treatment",
    "Waste scenario", "Separated waste", "Remaining waste",
}
_METADATA = {
    "PlatformId", "Category type", "Process identifier", "Type", "Process name",
    "Status", "Time period", "Geography", "Technology", "Representativeness",
    "Multiple output allocation", "Substitution allocation", "Cut off rules",
    "Capital goods", "Boundary with nature", "Infrastructure", "Date", "Record",
    "Generator", "External documents", "Literature references", "Collection method",
    "Data treatment", "Verification", "Comment", "Allocation rules",
    "System description",
}
_TECHNOSPHERE = {"Materials/fuels", "Electricity/heat", "Waste to treatment"}
_ELEMENTARY = {
    "Resources", "Emissions to air", "Emissions to water", "Emissions to soil",
    "Final waste flows", "Non material emissions", "Social issues", "Economic issues",
}


def export_simapro(bundle: dict[str, Any], model_id: str | None = None) -> bytes:
    """Export a selected PRISM Model closure as a SimaPro process CSV file."""
    prepared = prepare_export_bundle(bundle, model_id)
    processes = prepared["processes"]
    if not processes:
        raise InterchangeError("SIMAPRO_NO_PROCESSES", "SimaPro export requires at least one Process.")
    by_id = {row["id"]: row for values in prepared.values() for row in values}
    provider_by_exchange = _model_providers(prepared["models"], by_id)
    reference_names = {
        process["id"]: _reference_product_name(process, by_id) for process in processes
    }

    stream = io.StringIO(newline="")
    stream.write("{SimaPro 9.6.0.0}\r\n")
    stream.write("{processes}\r\n")
    stream.write("{Date: 01/01/1970}\r\n")
    stream.write("{Time: 00:00:00}\r\n")
    stream.write("{Project: PRISM export}\r\n")
    stream.write("{CSV Format version: 9.0.0}\r\n")
    stream.write("{CSV separator: Semicolon}\r\n")
    stream.write("{Decimal separator: .}\r\n")
    stream.write("{Date separator: /}\r\n")
    stream.write("{Short date format: M/d/yyyy}\r\n")
    stream.write("{Export platform IDs: Yes}\r\n\r\n")
    writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
    for process in sorted(processes, key=lambda row: row["id"]):
        _write_process(writer, process, by_id, provider_by_exchange, reference_names)
    return stream.getvalue().encode("utf-8-sig")


def preview_simapro(package: bytes) -> dict[str, Any]:
    """Convert a SimaPro process CSV file into a PRISM import preview."""
    if len(package) > MAX_PACKAGE_BYTES:
        raise InterchangeError(
            "PACKAGE_TOO_LARGE", "The uploaded file exceeds the 25 MB limit.",
            details={"bytes": len(package), "limit_bytes": MAX_PACKAGE_BYTES}, status_code=413,
        )
    text = _decode(package)
    header_lines, body = _split_header(text)
    kind = next((line[1:-1].strip().casefold() for line in header_lines if line[1:-1].strip().casefold() in {"processes", "methods", "product stages"}), "processes")
    if kind != "processes":
        raise InterchangeError(
            "UNSUPPORTED_SIMAPRO_EXPORT_TYPE",
            "Only SimaPro process CSV files can be imported; methods and product stages are not supported.",
            details={"type": kind},
        )
    delimiter = _header_delimiter(header_lines)
    decimal = _header_value(header_lines, "Decimal separator:") or "."
    project = _header_value(header_lines, "Project:") or "SimaPro import"
    try:
        rows = list(csv.reader(io.StringIO(body), delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise InterchangeError("INVALID_SIMAPRO_CSV", "The SimaPro CSV rows are malformed.") from exc
    blocks = _process_blocks(rows)
    if not blocks:
        raise InterchangeError("EMPTY_SIMAPRO_CSV", "The SimaPro CSV contains no Process blocks.")

    warnings: list[dict[str, Any]] = []
    specs = [_parse_process(block, decimal, index, warnings) for index, block in enumerate(blocks)]
    flow_specs: dict[str, dict[str, Any]] = {}
    unit_names: set[str] = set()
    providers: dict[str, list[str]] = {}
    process_rows: list[dict[str, Any]] = []
    consumer_products: list[tuple[str, str]] = []
    for spec in specs:
        exchanges = []
        reference_internal_id = None
        for index, exchange in enumerate(spec["exchanges"], start=1):
            flow_id = exchange["flow_id"]
            existing = flow_specs.get(flow_id)
            if existing and (existing["unit"] != exchange["unit"] or existing["elementary"] != exchange["elementary"]):
                raise InterchangeError(
                    "SIMAPRO_FLOW_CONFLICT",
                    f"Flow '{flow_id}' is used with incompatible units or flow types.",
                    details={"flow_id": flow_id},
                )
            flow_specs.setdefault(flow_id, exchange)
            unit_names.add(exchange["unit"])
            exchanges.append({
                "dataSetInternalID": index,
                "referenceToFlowDataSet": {"type": "flow", "refObjectId": flow_id, "shortDescription": exchange["name"]},
                "exchangeDirection": exchange["direction"],
                "meanAmount": exchange["amount"],
                "resultingAmount": exchange["amount"],
                "generalComment": _lang_text(exchange.get("comment")),
            })
            if exchange["reference"]:
                reference_internal_id = index
            if exchange["section"] == "Products":
                providers.setdefault(exchange["name"], []).append(spec["id"])
            elif exchange["section"] in _TECHNOSPHERE:
                consumer_products.append((spec["id"], exchange["name"]))
        if reference_internal_id is None:
            output = next((item["dataSetInternalID"] for item in exchanges if item["exchangeDirection"] == "Output"), None)
            reference_internal_id = output
            warnings.append(_warning("SIMAPRO_REFERENCE_OUTPUT_INFERRED", f"Reference output inferred for Process '{spec['name']}'.", process_id=spec["id"]))
        if reference_internal_id is None:
            raise InterchangeError("SIMAPRO_PROCESS_WITHOUT_OUTPUT", f"Process '{spec['name']}' has no product output.")
        process_rows.append(_process_row(spec, exchanges, reference_internal_id))

    connections: set[tuple[str, str]] = set()
    for consumer, product_name in consumer_products:
        candidates = sorted(set(providers.get(product_name, [])))
        if len(candidates) == 1:
            connections.add((candidates[0], consumer))
        elif len(candidates) > 1:
            warnings.append(_warning("AMBIGUOUS_SIMAPRO_PRODUCT_LINK", f"Product '{product_name}' has multiple providers; no Model connection was created.", product=product_name, providers=candidates))
        else:
            warnings.append(_warning("UNRESOLVED_SIMAPRO_PRODUCT_LINK", f"Product input '{product_name}' has no provider in this file.", product=product_name, consumer_process_id=consumer))

    unit_groups, properties, unit_refs = _reference_rows(unit_names)
    flows = [_flow_row(spec, unit_refs[spec["unit"]]) for _, spec in sorted(flow_specs.items())]
    model = _model_row(project, process_rows, sorted(connections))
    datasets = [model, *process_rows, *flows, *properties, *unit_groups]
    datasets.sort(key=lambda row: (row["type"], row["name"].casefold(), row["id"]))
    warnings.append(_warning(
        "SIMAPRO_MODEL_RECONSTRUCTED",
        "SimaPro process CSV has no product-system graph; one PRISM Model was reconstructed from product-name links.",
    ))
    return {
        "format": "simapro-csv", "valid": True,
        "summary": {"model": 1, "process": len(process_rows), "flow": len(flows), "flow_property": len(properties), "unit_group": len(unit_groups), "source": 0, "contact": 0},
        "datasets": datasets, "matches": [], "warnings": warnings, "errors": [],
    }


def looks_like_simapro_csv(package: bytes) -> bool:
    return package[:256].lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{SimaPro ")


def _write_process(writer: Any, process: dict[str, Any], by_id: dict[str, dict[str, Any]], provider_by_exchange: dict[tuple[str, str], str], reference_names: dict[str, str]) -> None:
    payload = process["payload"]
    location = _dig(payload, "processInformation", "geography", "location") or "GLO"
    pairs = [
        ("PlatformId", process["id"]), ("Category type", "material"),
        ("Process identifier", process["id"]), ("Type", "Unit process"),
        ("Process name", process["name"]), ("Status", "Draft"),
        ("Time period", "Unspecified"), ("Geography", location),
        ("Technology", "Unspecified"), ("Representativeness", "Unspecified"),
        ("Multiple output allocation", "Unspecified"), ("Substitution allocation", "Unspecified"),
        ("Cut off rules", "Unspecified"), ("Capital goods", "Unspecified"),
        ("Boundary with nature", "Unspecified"), ("Infrastructure", "No"),
        ("Date", "1/1/1970"), ("Record", "PRISM"), ("Generator", "PRISM"),
        ("Comment", process.get("description") or ""), ("System description", "PRISM export"),
    ]
    writer.writerow(["Process"]); writer.writerow([])
    for key, value in pairs:
        writer.writerow([key]); writer.writerow([value]); writer.writerow([])

    sections: dict[str, list[list[Any]]] = {name: [] for name in _SECTIONS if name not in {"Input parameters", "Calculated parameters"}}
    reference = _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    for exchange in _dicts(payload.get("exchanges")):
        flow_id = _ref_id(exchange.get("referenceToFlowDataSet"))
        flow = by_id.get(flow_id or "")
        if not flow:
            continue
        unit = _flow_unit(flow, by_id)
        amount = _finite(exchange.get("resultingAmount", exchange.get("meanAmount", 0)), "exchange amount")
        direction = str(exchange.get("exchangeDirection") or "Input").casefold()
        elementary = str(_dig(flow, "payload", "modellingAndValidation", "typeOfDataSet") or "").casefold().startswith("elementary")
        comment = _comment_with_id(_first_text(exchange.get("generalComment")), flow["id"])
        name = str(_dig(exchange, "referenceToFlowDataSet", "shortDescription") or flow["name"])
        is_reference = exchange.get("dataSetInternalID") == reference and direction == "output"
        if elementary:
            section, subcategory = _elementary_section(flow, direction)
            sections[section].append([name, subcategory, unit, _number(abs(amount)), "Undefined", "0", "0", "0", comment])
        elif direction == "output":
            sections["Products"].append([name, unit, _number(abs(amount)), "100" if is_reference else "0", "not defined", "PRISM", comment])
        else:
            provider = provider_by_exchange.get((process["id"], flow["id"]))
            linked_name = reference_names.get(provider, name)
            sections["Materials/fuels"].append([linked_name, unit, _number(abs(amount)), "Undefined", "0", "0", "0", comment])
    for section in ("Products", "Avoided products", "Resources", "Materials/fuels", "Electricity/heat", "Emissions to air", "Emissions to water", "Emissions to soil", "Final waste flows", "Non material emissions", "Social issues", "Economic issues", "Waste to treatment"):
        writer.writerow([section])
        for row in sections[section]: writer.writerow(row)
        writer.writerow([])
    writer.writerow(["End"]); writer.writerow([]); writer.writerow([])


def _split_header(text: str) -> tuple[list[str], str]:
    lines = text.lstrip("\ufeff \t\r\n").splitlines(keepends=True)
    header: list[str] = []
    index = 0
    while index < len(lines) and lines[index].strip().startswith("{"):
        header.append(lines[index].strip().strip('"'))
        index += 1
    if not header or not header[0].startswith("{SimaPro "):
        raise InterchangeError("INVALID_SIMAPRO_HEADER", "The file does not have a valid SimaPro CSV header.")
    return header, "".join(lines[index:])


def _header_value(lines: list[str], label: str) -> str | None:
    for line in lines:
        value = line.strip("{}\"")
        if value.casefold().startswith(label.casefold()):
            return value[len(label):].strip().strip("'\"")
    return None


def _header_delimiter(lines: list[str]) -> str:
    value = (_header_value(lines, "CSV separator:") or "Semicolon").casefold()
    delimiter = {"semicolon": ";", "comma": ",", "tab": "\t"}.get(value, value)
    if len(delimiter) != 1:
        raise InterchangeError("INVALID_SIMAPRO_DELIMITER", f"Unsupported SimaPro CSV separator '{value}'.")
    return delimiter


def _process_blocks(rows: list[list[str]]) -> list[list[list[str]]]:
    blocks: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for raw in rows:
        row = [value.replace("\x7f", "\n").strip() for value in raw]
        first = row[0] if row else ""
        if first == "Process" and len([x for x in row if x]) == 1:
            if current is not None: blocks.append(current)
            current = []
        elif current is not None and first == "End" and len([x for x in row if x]) == 1:
            blocks.append(current); current = None
        elif current is not None:
            current.append(row)
    if current is not None: blocks.append(current)
    return blocks


def _parse_process(block: list[list[str]], decimal: str, ordinal: int, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in block if any(row)]
    metadata: dict[str, str] = {}
    sections: dict[str, list[list[str]]] = {}
    i = 0
    while i < len(rows) and rows[i][0] not in _SECTIONS:
        key = rows[i][0]
        if key not in _METADATA:
            warnings.append(_warning("UNSUPPORTED_SIMAPRO_PROCESS_FIELD", f"Ignored SimaPro Process field '{key}'.", field=key))
        if i + 1 < len(rows) and rows[i + 1][0] not in _METADATA and rows[i + 1][0] not in _SECTIONS:
            metadata[key] = ";".join(rows[i + 1]).strip()
            i += 2
        else:
            metadata[key] = ""
            i += 1
    while i < len(rows):
        section = rows[i][0]
        i += 1
        data: list[list[str]] = []
        while i < len(rows) and rows[i][0] not in _SECTIONS:
            data.append(rows[i]); i += 1
        sections[section] = data
    process_id = next((value for value in (metadata.get("PlatformId"), metadata.get("Process identifier")) if _is_uuid(value)), None)
    name = metadata.get("Process name") or next((row[0] for row in sections.get("Products", []) if row), None) or f"SimaPro process {ordinal + 1}"
    process_id = process_id or _uid("process", metadata.get("Process identifier", ""), name, str(ordinal))
    exchanges: list[dict[str, Any]] = []
    for section, data in sections.items():
        if section not in _SECTIONS:
            continue
        if section in {"Input parameters", "Calculated parameters", "Waste scenario", "Separated waste", "Remaining waste"}:
            if data:
                warnings.append(_warning("UNSUPPORTED_SIMAPRO_SECTION", f"Ignored unsupported SimaPro section '{section}'.", process_id=process_id, section=section))
            continue
        for row_index, row in enumerate(data):
            try:
                exchange = _parse_exchange(section, row, decimal, process_id, row_index)
            except (IndexError, ValueError) as exc:
                raise InterchangeError("INVALID_SIMAPRO_EXCHANGE", f"Process '{name}' has a malformed '{section}' row.", details={"process_id": process_id, "section": section, "row": row_index + 1}) from exc
            exchanges.append(exchange)
    products = [item for item in exchanges if item["section"] in {"Products", "Waste treatment"}]
    for index, item in enumerate(products):
        item["reference"] = index == 0
    return {"id": process_id, "name": name, "description": metadata.get("Comment", ""), "location": metadata.get("Geography") or "GLO", "exchanges": exchanges}


def _parse_exchange(section: str, row: list[str], decimal: str, process_id: str, ordinal: int) -> dict[str, Any]:
    elementary = section in _ELEMENTARY
    if section == "Products":
        name, unit, raw = row[0], row[1], row[2]
        comment = row[6] if len(row) > 6 else ""
        direction, reference = "Output", False
    elif section == "Avoided products":
        name, unit, raw = row[0], row[1], row[2]
        comment = row[7] if len(row) > 7 else ""
        direction, reference = "Output", False
    elif elementary:
        name, unit, raw = row[0], row[2], row[3]
        comment = row[8] if len(row) > 8 else ""
        direction, reference = ("Input" if section == "Resources" else "Output"), False
    elif section == "Waste treatment":
        name, unit, raw = row[0], row[1], row[2]
        comment = row[5] if len(row) > 5 else ""
        direction, reference = "Output", False
    else:
        name, unit, raw = row[0], row[1], row[2]
        comment = row[7] if len(row) > 7 else ""
        direction, reference = "Input", False
    flow_id = _flow_id(comment) or _uid("flow", "elementary" if elementary else "product", name, unit)
    amount = _parse_number(raw, decimal)
    return {"id": flow_id, "flow_id": flow_id, "name": name, "unit": unit or "unit", "amount": amount, "direction": direction, "reference": reference, "elementary": elementary, "section": section, "comment": _clean_marker(comment), "compartment": section}


def _process_row(spec: dict[str, Any], exchanges: list[dict[str, Any]], reference: int) -> dict[str, Any]:
    return _row(spec["id"], "process", spec["name"], spec["description"], {
        "processInformation": {
            "dataSetInformation": {"name": {"baseName": [{"lang": "en", "text": spec["name"]}], "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": [], "generalComment": _lang_text(spec["description"])},
            "quantitativeReference": {"referenceToReferenceFlow": reference}, "geography": {"location": spec["location"]},
        },
        "modellingAndValidation": {"typeOfDataSet": "Unit process, single operation"},
        "administrativeInformation": {"dataSetVersion": "01.00.000"}, "exchanges": exchanges,
    })


def _reference_rows(units: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    groups, properties, refs = [], [], {}
    for unit in sorted(units):
        group_id, property_id = _uid("unit-group", unit), _uid("flow-property", unit)
        refs[unit] = property_id
        groups.append(_row(group_id, "unit_group", f"Units of {unit}", f"Reconstructed from SimaPro unit '{unit}'.", {"unitGroupInformation": {"dataSetInformation": {"name": [{"lang": "en", "text": f"Units of {unit}"}], "classification": [], "generalComment": []}, "quantitativeReference": {"referenceToReferenceUnit": 1}}, "units": [{"dataSetInternalID": 1, "name": unit, "meanValue": 1.0, "generalComment": []}], "administrativeInformation": {"dataSetVersion": "01.00.000"}}))
        properties.append(_row(property_id, "flow_property", unit, f"Reconstructed from SimaPro unit '{unit}'.", {"flowPropertiesInformation": {"dataSetInformation": {"name": [{"lang": "en", "text": unit}], "classification": [], "generalComment": []}, "quantitativeReference": {"referenceToReferenceUnitGroup": {"type": "unit_group", "refObjectId": group_id, "shortDescription": f"Units of {unit}"}}}, "administrativeInformation": {"dataSetVersion": "01.00.000"}}))
    return groups, properties, refs


def _flow_row(spec: dict[str, Any], property_id: str) -> dict[str, Any]:
    description = spec.get("comment") or ""
    return _row(spec["flow_id"], "flow", spec["name"], description, {"flowInformation": {"dataSetInformation": {"name": {"baseName": [{"lang": "en", "text": spec["name"]}], "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": [spec["compartment"]] if spec["elementary"] else [], "generalComment": _lang_text(description)}, "quantitativeReference": {"referenceToReferenceFlowProperty": 1}}, "modellingAndValidation": {"typeOfDataSet": "Elementary flow" if spec["elementary"] else "Product flow"}, "flowProperties": [{"dataSetInternalID": 1, "referenceToFlowPropertyDataSet": {"type": "flow_property", "refObjectId": property_id, "shortDescription": spec["unit"]}, "meanValue": 1.0, "generalComment": []}], "administrativeInformation": {"dataSetVersion": "01.00.000"}})


def _model_row(project: str, processes: list[dict[str, Any]], connections: list[tuple[str, str]]) -> dict[str, Any]:
    ids = sorted(row["id"] for row in processes); names = {row["id"]: row["name"] for row in processes}
    internal = {value: index for index, value in enumerate(ids, 1)}
    providers, consumers = {a for a, _ in connections}, {b for _, b in connections}
    sinks = sorted(consumers - providers) or ids
    return _row(_uid("model", project, *ids), "model", project, "Reconstructed from SimaPro product links.", {"modelInformation": {"dataSetInformation": {"name": {"baseName": [{"lang": "en", "text": project}], "treatmentStandardsRoutes": [], "mixAndLocationTypes": []}, "classification": [], "generalComment": []}, "quantitativeReference": {"referenceToReferenceProcess": internal[sinks[-1]]}}, "processInstances": [{"dataSetInternalID": internal[value], "referenceToProcess": {"type": "process", "refObjectId": value, "shortDescription": names[value]}, "multiplicationFactor": 1.0} for value in ids], "connections": [{"fromInstanceId": internal[a], "toInstanceId": internal[b]} for a, b in connections], "administrativeInformation": {"dataSetVersion": "01.00.000"}})


def _reference_product_name(process: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    payload = process["payload"]; reference = _dig(payload, "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    exchange = next((row for row in _dicts(payload.get("exchanges")) if row.get("dataSetInternalID") == reference), None)
    flow = by_id.get(_ref_id(exchange.get("referenceToFlowDataSet")) if exchange else "")
    return str(_dig(exchange or {}, "referenceToFlowDataSet", "shortDescription") or (flow or {}).get("name") or process["name"])


def _model_providers(models: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]) -> dict[tuple[str, str], str]:
    result = {}
    for model in models:
        instances = {row.get("dataSetInternalID"): _ref_id(row.get("referenceToProcess")) for row in _dicts(model["payload"].get("processInstances"))}
        for edge in _dicts(model["payload"].get("connections")):
            provider, consumer = instances.get(edge.get("fromInstanceId")), instances.get(edge.get("toInstanceId"))
            process = by_id.get(provider or ""); flow_id = _reference_flow_id(process) if process else None
            if provider and consumer and flow_id: result[(consumer, flow_id)] = provider
    return result


def _reference_flow_id(process: dict[str, Any]) -> str | None:
    reference = _dig(process, "payload", "processInformation", "quantitativeReference", "referenceToReferenceFlow")
    exchange = next((row for row in _dicts(_dig(process, "payload", "exchanges")) if row.get("dataSetInternalID") == reference), None)
    return _ref_id(exchange.get("referenceToFlowDataSet")) if exchange else None


def _flow_unit(flow: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    payload = flow["payload"]; ref = _dig(payload, "flowInformation", "quantitativeReference", "referenceToReferenceFlowProperty")
    factor = next((row for row in _dicts(payload.get("flowProperties")) if row.get("dataSetInternalID") == ref), None)
    prop = by_id.get(_ref_id(factor.get("referenceToFlowPropertyDataSet")) if factor else "")
    group = by_id.get(_ref_id(_dig(prop or {}, "payload", "flowPropertiesInformation", "quantitativeReference", "referenceToReferenceUnitGroup")) or "")
    unit_ref = _dig(group or {}, "payload", "unitGroupInformation", "quantitativeReference", "referenceToReferenceUnit")
    unit = next((row for row in _dicts(_dig(group or {}, "payload", "units")) if row.get("dataSetInternalID") == unit_ref), None)
    return str((unit or {}).get("name") or "unit")


def _elementary_section(flow: dict[str, Any], direction: str) -> tuple[str, str]:
    if direction == "input": return "Resources", "unspecified"
    values = _dig(flow, "payload", "flowInformation", "dataSetInformation", "classification")
    text = " ".join(str(x) for x in values).casefold() if isinstance(values, list) else ""
    if "water" in text: return "Emissions to water", "unspecified"
    if "soil" in text: return "Emissions to soil", "unspecified"
    return "Emissions to air", "unspecified"


def _decode(package: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try: return package.decode(encoding)
        except UnicodeDecodeError: pass
    raise InterchangeError("INVALID_SIMAPRO_ENCODING", "The SimaPro CSV must be UTF-8 or Windows-1252 encoded.")


def _parse_number(value: str, decimal: str) -> float:
    normalized = value.strip().replace(" ", "")
    if decimal == ",": normalized = normalized.replace(".", "").replace(",", ".")
    try:
        number = float(normalized)
    except ValueError:
        number = _numeric_expression(normalized)
    if not math.isfinite(number): raise ValueError("non-finite")
    return number


def _numeric_expression(value: str) -> float:
    """Evaluate constant arithmetic without names or function calls."""
    tree = ast.parse(value.replace("^", "**"), mode="eval")
    operators = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a ** b}
    unary = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool): return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in operators: return operators[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary: return unary[type(node.op)](visit(node.operand))
        raise ValueError("unsupported formula")

    return visit(tree)


def _number(value: float) -> str: return format(value, ".15g")
def _flow_id(comment: str) -> str | None:
    match = _FLOW_ID_RE.search(comment or ""); value = match.group(1) if match else None
    return value if _is_uuid(value) else None
def _clean_marker(comment: str) -> str: return _FLOW_ID_RE.sub("", comment or "").strip(" \n|")
def _comment_with_id(comment: str | None, flow_id: str) -> str: return f"{comment + chr(127) if comment else ''}PRISM-FLOW-ID: {flow_id}"
def _lang_text(value: str | None) -> list[dict[str, str]]: return [{"lang": "en", "text": value}] if value else []
def _row(row_id: str, kind: str, name: str, description: str | None, payload: dict[str, Any]) -> dict[str, Any]: return {"temporary_id": f"import:{kind}:{row_id}", "source_id": row_id, "id": row_id, "type": kind, "name": name, "description": description or "", "payload": payload, "decision": "create"}
def _warning(code: str, message: str, **details: Any) -> dict[str, Any]: return {"code": code, "message": message, **({"details": details} if details else {})}
def _dicts(value: Any) -> list[dict[str, Any]]: return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []
def _dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict): return None
        value = value.get(key)
    return value
def _ref_id(value: Any) -> str | None:
    result = value.get("refObjectId") if isinstance(value, dict) else None
    return result if isinstance(result, str) and result else None
def _first_text(value: Any) -> str | None:
    return next((x.get("text") for x in value if isinstance(x, dict) and isinstance(x.get("text"), str) and x["text"]), None) if isinstance(value, list) else None
def _uid(*parts: str) -> str: return str(uuid.uuid5(NS, "|".join(parts)))
def _is_uuid(value: Any) -> bool: return isinstance(value, str) and bool(_UUID_RE.match(value))
def _finite(value: Any, path: str) -> float:
    try: number = float(value)
    except (TypeError, ValueError) as exc: raise InterchangeError("INVALID_SIMAPRO_NUMBER", f"'{path}' must be a number.") from exc
    if not math.isfinite(number): raise InterchangeError("INVALID_SIMAPRO_NUMBER", f"'{path}' must be finite.")
    return number
