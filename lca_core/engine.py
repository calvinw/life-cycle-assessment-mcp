"""Brightway 2.5 calculation and inventory engine.

Accepts a product graph as a YAML string.
Returns a structured dict with LCI totals, LCIA scores, and scaling vector.
No external server required — all computation runs in-process via Brightway.

Run scripts/setup_databases.py once before using this module.
"""

import hashlib
import math
import os
import pathlib
import re
import tarfile
import threading
import urllib.request
import uuid
from contextlib import contextmanager

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Must be set before bw2data is imported; directory must exist
if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = ROOT / "brightway_data"
    _bw_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

import yaml
import numpy as np
import bw2data as bd
import bw2calc as bc

from .models import LcaCoreResult

BRIGHTWAY_PROJECT = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
BIOSPHERE_DB = "biosphere3"
LEGACY_FOREGROUND_DB = "foreground"
FOREGROUND_DB_PREFIX = "foreground_request_"

NUMERIC_ABS_TOLERANCE = 1e-12
NUMERIC_REL_TOLERANCE = 1e-9

# URL of the pre-built Brightway database tarball on GitHub Releases.
# To update: build a new tarball (see docs/bafu_database_setup.md) and bump this URL.
TARBALL_URL = (
    "https://github.com/calvinw/life-cycle-assessment-mcp"
    "/releases/download/lca-data-v2/brightway_bafu_v1.tar.gz"
)

_db_lock = threading.Lock()
_calculation_lock = threading.RLock()
_startup_databases_ready = False


def _ensure_search_projection():
    """Build the disposable search database when it is missing or stale."""
    from .search import build_search_database, get_projection_status

    status = get_projection_status(project=BRIGHTWAY_PROJECT)
    if status.get("fresh"):
        return status

    reason = status.get("reason", "Search projection is unavailable")
    print(f"[lca_engine] {reason} — rebuilding search projection...")
    build_search_database(databases=["bafu"], project=BRIGHTWAY_PROJECT)
    status = get_projection_status(project=BRIGHTWAY_PROJECT)
    if not status.get("fresh"):
        raise RuntimeError(
            "Search projection build completed but freshness validation failed: "
            f"{status.get('reason', 'unknown reason')}"
        )
    return status


def _ensure_databases():
    """Ensure Brightway data and its searchable projection are production-ready."""
    global _startup_databases_ready
    if _startup_databases_ready:
        return

    with _db_lock:
        if _startup_databases_ready:
            return

        bd.projects.set_current(BRIGHTWAY_PROJECT)
        # Versions before result schema 2 reused this persistent scratch
        # database. It contains no authoritative user data and must not survive
        # startup now that foreground calculations are request-isolated.
        if LEGACY_FOREGROUND_DB in bd.databases:
            del bd.databases[LEGACY_FOREGROUND_DB]
        if "bafu" not in bd.databases:
            bw_dir = pathlib.Path(os.environ["BRIGHTWAY2_DIR"])
            tarball = bw_dir / "brightway_bafu_v1.tar.gz"
            print(f"[lca_engine] bafu database not found — downloading from GitHub releases...")
            urllib.request.urlretrieve(TARBALL_URL, tarball)
            print(
                f"[lca_engine] Downloaded {tarball.stat().st_size // 1024 // 1024} MB "
                "— extracting..."
            )
            with tarfile.open(tarball, "r:gz") as tf:
                tf.extractall(bw_dir.parent)
            tarball.unlink()
            print(f"[lca_engine] Database ready — {len(bd.Database('bafu'))} bafu processes.")

        _ensure_search_projection()
        _startup_databases_ready = True

# Index: (lowercase name, compartment) → activity key — built once on first lookup
_FLOW_INDEX: dict | None = None

# Common-name → ecoinvent/biosphere3 name aliases (case-insensitive, applied at lookup time)
_FLOW_ALIASES: dict[str, str] = {
    "co2": "carbon dioxide, fossil",
    "carbon dioxide": "carbon dioxide, fossil",
    "ch4": "methane, fossil",
    "methane": "methane, fossil",
    "n2o": "dinitrogen monoxide",
    "nitrous oxide": "dinitrogen monoxide",
    "nox": "nitrogen oxides",
    "sox": "sulfur dioxide",
}


def _ensure_project():
    _ensure_databases()
    bd.projects.set_current(BRIGHTWAY_PROJECT)


def _load_spec(product_graph_yaml: str) -> dict:
    text = product_graph_yaml.strip()
    if text.startswith("---"):
        _, fm, _ = text.split("---", 2)
        spec = yaml.safe_load(fm)
    else:
        spec = yaml.safe_load(text)
    _validate_spec(spec)
    return spec


def _require_finite(value, path: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number.")
    return result


def _validate_spec(spec: dict) -> None:
    """Validate identity and numeric invariants needed by every calculation."""
    if not isinstance(spec, dict):
        raise ValueError("product_graph must contain a YAML mapping.")

    processes = spec.get("processes")
    if not isinstance(processes, list) or not processes:
        raise ValueError("product_graph.processes must be a non-empty list.")

    functional_unit = spec.get("functional_unit")
    if not isinstance(functional_unit, dict):
        raise ValueError("product_graph.functional_unit must be a mapping.")
    _require_finite(functional_unit.get("amount"), "functional_unit.amount")
    if not functional_unit.get("unit"):
        raise ValueError("functional_unit.unit is required.")

    names: set[str] = set()
    output_flows: set[str] = set()
    for proc_index, proc in enumerate(processes):
        path = f"processes[{proc_index}]"
        if not isinstance(proc, dict):
            raise ValueError(f"{path} must be a mapping.")
        name = proc.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path}.name must be a non-empty string.")
        if name in names:
            raise ValueError(f"Duplicate process name '{name}' is not allowed.")
        names.add(name)

        reference_output = proc.get("reference_output")
        if not isinstance(reference_output, dict):
            raise ValueError(f"{path}.reference_output must be a mapping.")
        flow = reference_output.get("flow")
        if not isinstance(flow, str) or not flow.strip():
            raise ValueError(f"{path}.reference_output.flow is required.")
        if flow in output_flows:
            raise ValueError(
                f"Product flow '{flow}' has more than one foreground provider."
            )
        output_flows.add(flow)
        output_amount = _require_finite(
            reference_output.get("amount"), f"{path}.reference_output.amount"
        )
        if abs(output_amount) <= NUMERIC_ABS_TOLERANCE:
            raise ValueError(f"{path}.reference_output.amount must be non-zero.")

        for collection in ("inputs", "emissions", "resources"):
            rows = proc.get(collection, [])
            if not isinstance(rows, list):
                raise ValueError(f"{path}.{collection} must be a list.")
            for row_index, row in enumerate(rows):
                row_path = f"{path}.{collection}[{row_index}]"
                if not isinstance(row, dict):
                    raise ValueError(f"{row_path} must be a mapping.")
                if not isinstance(row.get("flow"), str) or not row["flow"].strip():
                    raise ValueError(f"{row_path}.flow is required.")
                _require_finite(row.get("amount"), f"{row_path}.amount")

    reference_process = spec.get("reference_process")
    if reference_process not in names:
        raise ValueError(
            f"Reference process '{reference_process}' does not match a process name."
        )
    lcia = spec.get("lcia")
    if not isinstance(lcia, dict) or not lcia.get("method_name"):
        raise ValueError("lcia.method_name is required.")


def _stable_id(kind: str, *parts: object) -> str:
    canonical = "\x1f".join(str(part) for part in parts)
    slug_source = str(parts[0]) if parts else kind
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-")[:48]
    slug = slug or "item"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{slug}:{digest}"


def _process_ids(spec: dict) -> dict[str, str]:
    return {
        proc["name"]: _stable_id("process", proc["name"])
        for proc in spec["processes"]
    }


def _declared_flow_units(spec: dict) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    product_units = {
        item["name"]: item["unit"]
        for item in spec.get("products", [])
        if isinstance(item, dict) and item.get("name") and item.get("unit")
    }
    elementary_units: dict[tuple[str, str], str] = {}
    elementary = spec.get("elementary_flows", {})
    if isinstance(elementary, dict):
        for kind in ("emissions", "resources"):
            for item in elementary.get(kind, []):
                if isinstance(item, dict) and item.get("name") and item.get("unit"):
                    elementary_units[(kind, item["name"])] = item["unit"]
    return product_units, elementary_units


def _exchange_unit(
    exchange: dict,
    *,
    path: str,
    declared_units: dict[str, str],
) -> str:
    unit = exchange.get("unit") or declared_units.get(exchange["flow"])
    if not isinstance(unit, str) or not unit:
        raise ValueError(
            f"Unit for {path} flow '{exchange['flow']}' is not declared."
        )
    return unit


def _sub_compartment_priority(flow) -> int:
    """Score a flow's sub-compartment: higher = preferred winner in _FLOW_INDEX.

    "unspecified" is the preferred biosphere3 sub-compartment that LCIA methods
    consistently characterize.  "indoor" and stratospheric sub-compartments
    are rarely included in LCIA CF tables and must not win the index slot.
    """
    cats = [c.lower() for c in flow.get("categories", [])]
    sub = cats[-1] if cats else ""
    if "unspecified" in sub:
        return 2
    if "indoor" in sub or "stratosphere" in sub:
        return 0
    return 1


def _build_flow_index():
    global _FLOW_INDEX
    _FLOW_INDEX = {}
    _priority: dict = {}
    for flow in bd.Database(BIOSPHERE_DB):
        name_key = flow.get("name", "").lower()
        compartment = flow.get("compartment", "")
        if not compartment:
            cats = [c.lower() for c in flow.get("categories", [])]
            cat_str = " ".join(cats)
            if "air" in cat_str:
                compartment = "air"
            elif "water" in cat_str or "freshwater" in cat_str:
                compartment = "water"
            elif "soil" in cat_str or "ground" in cat_str:
                compartment = "ground"
            elif "resource" in cat_str:
                compartment = "resource"
            else:
                compartment = "other"
        key = (name_key, compartment)
        score = _sub_compartment_priority(flow)
        if score > _priority.get(key, -1):
            _FLOW_INDEX[key] = flow.key
            _priority[key] = score


def _find_biosphere_flow(name: str, compartment: str):
    """Look up a flow in biosphere3 by name and compartment."""
    global _FLOW_INDEX
    if _FLOW_INDEX is None:
        _build_flow_index()
    canonical = _FLOW_ALIASES.get(name.lower(), name.lower())
    key = _FLOW_INDEX.get((canonical, compartment.lower()))
    if key:
        try:
            return bd.get_activity(key)
        except Exception:
            pass
    return None


def _compartment_for_emission(em: dict) -> str:
    return em.get("compartment", "air")


def _compartment_for_resource(res: dict) -> str:
    comp = res.get("compartment", "water")
    return comp


def _build_foreground_db(spec: dict, database_name: str) -> tuple[dict, dict, dict]:
    """Build (or rebuild) the foreground database from a parsed spec.

    Returns foreground activities, product providers, and the exact background
    provider selected for each ``(process_index, input_index)`` pair.
    """
    fg = bd.Database(database_name)
    fg.register()

    activities: dict = {}
    product_to_activity: dict = {}
    background_providers: dict = {}

    for proc_index, proc in enumerate(spec["processes"]):
        ref = proc["reference_output"]
        act = fg.new_activity(
            code=proc["name"],
            name=proc["name"],
            unit=ref.get("unit", "kg"),
            location="GLO",
        )
        act.save()
        activities[proc["name"]] = act
        product_to_activity[ref["flow"]] = act

    for proc in spec["processes"]:
        act = activities[proc["name"]]
        ref = proc["reference_output"]

        act.new_exchange(
            input=act,
            amount=float(ref["amount"]),
            type="production",
        ).save()

        for input_index, inp in enumerate(proc.get("inputs", [])):
            db_name = inp.get("database")
            if db_name:
                bg_db = bd.Database(db_name)
                location = inp.get("location")
                code = inp.get("code")
                if code:
                    try:
                        provider = bd.get_activity((db_name, code))
                    except Exception as exc:
                        raise ValueError(
                            f"Background activity code '{code}' not found "
                            f"in database '{db_name}'."
                        ) from exc
                else:
                    matches = [
                        activity
                        for activity in bg_db
                        if activity["name"] == inp["flow"]
                        and (
                            location is None
                            or activity.get("location") == location
                        )
                    ]
                    if len(matches) > 1:
                        raise ValueError(
                            f"Background flow '{inp['flow']}' [{location}] is "
                            f"ambiguous in database '{db_name}'; specify code."
                        )
                    provider = matches[0] if matches else None
                if provider is None:
                    raise ValueError(
                        f"Background flow '{inp['flow']}' [{location}] not found "
                        f"in database '{db_name}'."
                    )
                background_providers[(proc_index, input_index)] = provider
            else:
                provider = product_to_activity.get(inp["flow"])
                if provider is None:
                    raise ValueError(
                        f"Input flow '{inp['flow']}' in process '{proc['name']}' "
                        f"has no provider in this product graph."
                    )
            act.new_exchange(
                input=provider,
                amount=float(inp["amount"]),
                type="technosphere",
            ).save()

        for em in proc.get("emissions", []):
            compartment = _compartment_for_emission(em)
            flow = _find_biosphere_flow(em["flow"], compartment)
            if flow is None:
                raise ValueError(
                    f"Emission flow '{em['flow']}' (compartment: {compartment}) "
                    f"not found in '{BIOSPHERE_DB}'. "
                    f"Check the flow name and compartment in your product graph."
                )
            act.new_exchange(
                input=flow,
                amount=float(em["amount"]),
                type="biosphere",
            ).save()

        for res in proc.get("resources", []):
            compartment = _compartment_for_resource(res)
            flow = _find_biosphere_flow(res["flow"], compartment)
            if flow is None:
                raise ValueError(
                    f"Resource flow '{res['flow']}' (compartment: {compartment}) "
                    f"not found in '{BIOSPHERE_DB}'. "
                    f"Check the flow name and compartment in your product graph."
                )
            act.new_exchange(
                input=flow,
                amount=float(res["amount"]),
                type="biosphere",
            ).save()

    return activities, product_to_activity, background_providers


@contextmanager
def _request_foreground(spec: dict):
    """Create isolated foreground state and always remove it after the request.

    Brightway project and metadata state is process-global. The lock covers the
    complete calculation, while the unique database name prevents a failed or
    interrupted request from reusing another request's foreground activities.
    """
    database_name = f"{FOREGROUND_DB_PREFIX}{uuid.uuid4().hex}"
    with _calculation_lock:
        try:
            foreground = _build_foreground_db(spec, database_name)
            yield foreground
        finally:
            if database_name in bd.databases:
                del bd.databases[database_name]


def _contribution_category(
    lca,
    spec: dict,
    activities: dict,
    label: str,
    unit: str,
) -> dict:
    """Build exclusive foreground process scores for the active LCIA method."""
    column_totals = np.asarray(lca.characterized_inventory.sum(axis=0)).ravel()
    act_dict = lca.dicts.activity if hasattr(lca, "dicts") else lca.activity_dict
    process_ids = _process_ids(spec)
    total_score = float(lca.score)
    process_rows = []
    foreground_total = 0.0

    for proc in spec["processes"]:
        name = proc["name"]
        act = activities[name]
        node_id = act.id if hasattr(lca, "dicts") else act.key
        column = act_dict.get(node_id)
        direct_score = (
            float(column_totals[column])
            if column is not None and column < len(column_totals)
            else 0.0
        )
        foreground_total += direct_score
        percentage = (
            None
            if abs(total_score) <= NUMERIC_ABS_TOLERANCE
            else direct_score / total_score * 100.0
        )
        process_rows.append(
            {
                "process_id": process_ids[name],
                "process_name": name,
                "direct_score": direct_score,
                "percentage": percentage,
                "scope": "foreground",
            }
        )

    residual_score = total_score - foreground_total
    if not math.isclose(
        foreground_total + residual_score,
        total_score,
        rel_tol=NUMERIC_REL_TOLERANCE,
        abs_tol=NUMERIC_ABS_TOLERANCE,
    ):
        raise RuntimeError(f"Process contributions do not reconcile for '{label}'.")

    return {
        "id": _stable_id("impact", spec["lcia"]["method_name"], label),
        "label": label,
        "unit": unit,
        "total_score": total_score,
        "processes": process_rows,
        "residual_score": residual_score,
    }


def _build_sankey(
    spec: dict,
    scaling_vector: dict[str, float],
    background_providers: dict,
) -> dict:
    """Build a renderer-neutral graph from YAML using the solved scaling state."""
    process_ids = _process_ids(spec)
    product_units, elementary_units = _declared_flow_units(spec)
    product_providers = {
        proc["reference_output"]["flow"]: proc["name"]
        for proc in spec["processes"]
    }
    nodes: list[dict] = []
    links: list[dict] = []
    node_ids: set[str] = set()
    link_occurrences: dict[tuple[str, str, str, str], int] = {}

    def add_node(node: dict) -> None:
        if node["id"] not in node_ids:
            node_ids.add(node["id"])
            nodes.append(node)

    def add_link(
        *,
        source: str,
        target: str,
        kind: str,
        flow_name: str,
        amount: float,
        unit: str,
    ) -> None:
        if abs(amount) <= NUMERIC_ABS_TOLERANCE:
            return
        identity = (source, target, kind, flow_name)
        occurrence = link_occurrences.get(identity, 0)
        link_occurrences[identity] = occurrence + 1
        links.append(
            {
                "id": _stable_id("link", kind, source, target, flow_name, occurrence),
                "source": source,
                "target": target,
                "kind": kind,
                "flow_name": flow_name,
                "amount": amount,
                "unit": unit,
            }
        )

    for proc in spec["processes"]:
        name = proc["name"]
        add_node(
            {
                "id": process_ids[name],
                "label": name,
                "kind": "process",
                "process_name": name,
                "scope": "foreground",
            }
        )

    for proc_index, proc in enumerate(spec["processes"]):
        name = proc["name"]
        target = process_ids[name]
        scale = scaling_vector.get(name, 0.0)

        for input_index, inp in enumerate(proc.get("inputs", [])):
            db_name = inp.get("database")
            if db_name:
                provider = background_providers[(proc_index, input_index)]
                provider_key = provider.key
                provider_name = provider.get("name", inp["flow"])
                source = _stable_id(
                    "background-process", provider_key[0], provider_key[1]
                )
                add_node(
                    {
                        "id": source,
                        "label": provider_name,
                        "kind": "process",
                        "process_name": provider_name,
                        "scope": "background",
                    }
                )
            else:
                provider_name = product_providers.get(inp["flow"])
                if provider_name is None:
                    raise ValueError(
                        f"Input flow '{inp['flow']}' in process '{name}' has no provider."
                    )
                source = process_ids[provider_name]
            unit = _exchange_unit(
                inp,
                path=f"processes[{proc_index}].inputs[{input_index}]",
                declared_units=product_units,
            )
            add_link(
                source=source,
                target=target,
                kind="technosphere",
                flow_name=inp["flow"],
                amount=_require_finite(inp["amount"], "input amount") * scale,
                unit=unit,
            )

        for collection, node_kind, link_kind in (
            ("resources", "resource", "extraction"),
            ("emissions", "emission", "emission"),
        ):
            declared = {
                flow: unit
                for (kind, flow), unit in elementary_units.items()
                if kind == collection
            }
            for row_index, row in enumerate(proc.get(collection, [])):
                unit = _exchange_unit(
                    row,
                    path=f"processes[{proc_index}].{collection}[{row_index}]",
                    declared_units=declared,
                )
                compartment = row.get(
                    "compartment", "water" if collection == "resources" else "air"
                )
                flow_node_id = _stable_id(
                    node_kind, row["flow"], compartment, unit
                )
                add_node(
                    {
                        "id": flow_node_id,
                        "label": row["flow"],
                        "kind": node_kind,
                        "flow_name": row["flow"],
                    }
                )
                amount = _require_finite(row["amount"], f"{collection} amount") * scale
                add_link(
                    source=flow_node_id if link_kind == "extraction" else target,
                    target=target if link_kind == "extraction" else flow_node_id,
                    kind=link_kind,
                    flow_name=row["flow"],
                    amount=amount,
                    unit=unit,
                )

    reference_name = spec["reference_process"]
    reference_proc = next(
        proc for proc in spec["processes"] if proc["name"] == reference_name
    )
    final_flow = reference_proc["reference_output"]["flow"]
    final_node_id = _stable_id("final-product", final_flow, spec.get("name", ""))
    add_node(
        {
            "id": final_node_id,
            "label": spec["functional_unit"].get("description", final_flow),
            "kind": "final_product",
            "flow_name": final_flow,
        }
    )
    add_link(
        source=process_ids[reference_name],
        target=final_node_id,
        kind="final_product",
        flow_name=final_flow,
        amount=_require_finite(
            spec["functional_unit"]["amount"], "functional_unit.amount"
        ),
        unit=spec["functional_unit"]["unit"],
    )

    available_units = sorted({link["unit"] for link in links})
    return {"nodes": nodes, "links": links, "available_units": available_units}


def _ensure_finite_result(value, path: str = "result") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} contains a non-finite number.")
    if isinstance(value, dict):
        for key, item in value.items():
            _ensure_finite_result(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _ensure_finite_result(item, f"{path}[{index}]")


def run_analysis(product_graph_yaml: str) -> LcaCoreResult:
    spec = _load_spec(product_graph_yaml)

    with _calculation_lock:
        _ensure_project()
        with _request_foreground(spec) as (
            activities,
            _,
            background_providers,
        ):
            ref_proc_name = spec["reference_process"]
            ref_act = activities[ref_proc_name]
            fu_amount = float(spec["functional_unit"]["amount"])

            method_name = spec["lcia"]["method_name"]
            method_tuples = sorted(
                [m for m in bd.methods if len(m) >= 2 and m[0] == method_name],
                key=lambda m: m[-1],
            )
            if not method_tuples:
                raise ValueError(
                    f"LCIA method '{method_name}' not found. "
                    f"Run scripts/setup_databases.py to load methods."
                )

            # Compute inventory and the scaling solution exactly once.
            lca = bc.LCA(demand={ref_act: fu_amount}, method=method_tuples[0])
            lca.lci(factorize=True)

            scaling_vector: dict[str, float] = {}
            act_dict = (
                lca.dicts.activity if hasattr(lca, "dicts") else lca.activity_dict
            )
            for act_name, act in activities.items():
                node_id = act.id if hasattr(lca, "dicts") else act.key
                idx = act_dict.get(node_id)
                if idx is not None:
                    scaling_vector[act_name] = float(lca.supply_array[idx])

            # LCI totals retain their existing contract and meaning.
            lci: dict = {}
            total_inv = np.asarray(lca.inventory.sum(axis=1)).ravel()
            bio_dict = (
                lca.dicts.biosphere
                if hasattr(lca, "dicts")
                else lca.biosphere_dict
            )
            bio_db = bd.Database(BIOSPHERE_DB)
            for flow in bio_db:
                node_id = flow.id if hasattr(lca, "dicts") else flow.key
                idx = bio_dict.get(node_id)
                if idx is not None and idx < len(total_inv):
                    amount = float(total_inv[idx])
                    if abs(amount) > 1e-15:
                        lci[flow["name"]] = {
                            "amount": amount,
                            "unit": flow.get("unit", "kg"),
                            "type": flow.get("type", "emission"),
                        }

            lcia_results: dict = {}
            contribution_categories: list[dict] = []
            for method_index, method_tuple in enumerate(method_tuples):
                if method_index:
                    lca.switch_method(method_tuple)
                lca.lcia()
                label = " | ".join(method_tuple[1:])
                unit = bd.methods[method_tuple].get("unit", "")
                lcia_results[label] = {"score": float(lca.score), "unit": unit}
                contribution_categories.append(
                    _contribution_category(
                        lca, spec, activities, label=label, unit=unit
                    )
                )

            fu_spec = spec["functional_unit"]
            result: LcaCoreResult = {
                "name": spec.get("name", ""),
                "method": method_name,
                "functional_unit": (
                    f"{fu_amount} {fu_spec['unit']} — {fu_spec['description']}"
                ),
                "lci": lci,
                "lcia": lcia_results,
                "scaling_vector": scaling_vector,
                "result_schema_version": 2,
                "process_contributions": {
                    "categories": contribution_categories
                },
                "sankey": _build_sankey(
                    spec, scaling_vector, background_providers
                ),
            }
            _ensure_finite_result(result)
            return result


def get_contributions(product_graph_yaml: str, method_name: str, top_n: int = 10) -> dict:
    """
    Run contribution analysis for a single named impact category.

    Runs a fresh LCA and returns the top processes driving impact for the
    specified category, ranked by absolute score.

    method_name must substring-match a key in the LCIA results
    (e.g. "climate change", "acidification", "water use").
    Returns {method, score, unit, processes: [{activity, location, score, fraction}]}.
    """
    spec = _load_spec(product_graph_yaml)
    with _calculation_lock:
        _ensure_project()
        with _request_foreground(spec) as (activities, _, _):
            import bw2analyzer as ba

            method_name_full = spec["lcia"]["method_name"]
            method_tuples = sorted(
                [m for m in bd.methods if len(m) >= 2 and m[0] == method_name_full],
                key=lambda m: m[-1],
            )
            if not method_tuples:
                raise ValueError(f"LCIA method '{method_name_full}' not found.")

            target = next(
                (
                    m
                    for m in method_tuples
                    if method_name.lower() in " | ".join(m[1:]).lower()
                ),
                None,
            )
            if target is None:
                available = [" | ".join(m[1:]) for m in method_tuples]
                raise ValueError(
                    f"Method '{method_name}' not found. Available: {available}"
                )

            ref_act = activities[spec["reference_process"]]
            fu_amount = float(spec["functional_unit"]["amount"])
            lca = bc.LCA({ref_act: fu_amount}, target)
            lca.lci(factorize=True)
            lca.lcia()

            total = lca.score
            ca = ba.ContributionAnalysis()
            processes = []
            for score, _, act in ca.annotated_top_processes(lca, limit=top_n):
                try:
                    name = act["name"]
                    location = act.get("location", "")
                except Exception:
                    name = str(act)
                    location = ""
                processes.append({
                    "activity": name,
                    "location": location,
                    "score": float(score),
                    "fraction": float(score / total) if total else 0.0,
                })

            return {
                "method": " | ".join(target[1:]),
                "score": float(total),
                "unit": bd.methods[target].get("unit", ""),
                "processes": processes,
            }


def query_database(sql: str, limit: int = 100) -> dict:
    """Run read-only SQL against the searchable projection, never databases.db."""
    _ensure_project()
    from .search import query_search_database

    return query_search_database(sql, limit=limit, project=BRIGHTWAY_PROJECT)


def get_database_schema() -> dict:
    """Return the schema and freshness of the searchable projection."""
    _ensure_project()
    from .search import get_search_schema

    return get_search_schema(project=BRIGHTWAY_PROJECT)


def list_databases() -> list:
    """Return all databases installed in the current Brightway project."""
    _ensure_project()
    results = []
    for name in sorted(bd.databases):
        meta = bd.databases[name]
        results.append({
            "name": name,
            "size": meta.get("number", len(bd.Database(name))),
            "backend": meta.get("backend", "sqlite"),
            "depends": meta.get("depends", []),
        })
    return results


def search_database(query: str, database: str = "biosphere3", limit: int = 25) -> list:
    """Search projection activities without querying Brightway's SQLite file."""
    _ensure_project()
    from .search import search_activities

    results = search_activities(
        query,
        database=database,
        limit=limit,
        project=BRIGHTWAY_PROJECT,
    )
    return [
        {
            "name": result["name"],
            "reference_product": result.get("reference_product"),
            "location": result.get("location"),
            "categories": (result.get("categories_text") or "").split("::")
            if result.get("categories_text")
            else [],
            "unit": result.get("unit") or "",
            "type": result.get("type") or "",
            "key": [result["database"], result["code"]],
        }
        for result in results
    ]


def top_emissions(product_graph_yaml: str, method_name: str, top_n: int = 15) -> list:
    """
    Return the top biosphere flows (emissions/resources) driving impact for one
    LCIA category, ranked by absolute direct impact score.

    method_name must substring-match a key in the LCIA results
    e.g. "climate change", "acidification", "water use".

    Returns list of {flow, categories, unit, score, fraction}.
    """
    spec = _load_spec(product_graph_yaml)
    with _calculation_lock:
        _ensure_project()
        with _request_foreground(spec) as (activities, _, _):
            import bw2analyzer as ba

            method_name_full = spec["lcia"]["method_name"]
            method_tuples = sorted(
                [m for m in bd.methods if len(m) >= 2 and m[0] == method_name_full],
                key=lambda m: m[-1],
            )
            target = next(
                (
                    m
                    for m in method_tuples
                    if method_name.lower() in " | ".join(m[1:]).lower()
                ),
                None,
            )
            if target is None:
                available = [" | ".join(m[1:]) for m in method_tuples]
                raise ValueError(
                    f"Method '{method_name}' not found. Available: {available}"
                )

            ref_act = activities[spec["reference_process"]]
            fu_amount = float(spec["functional_unit"]["amount"])
            lca = bc.LCA({ref_act: fu_amount}, target)
            lca.lci(factorize=True)
            lca.lcia()

            total = lca.score
            ca = ba.ContributionAnalysis()
            rows = []
            for score, _, flow in ca.annotated_top_emissions(lca, limit=top_n):
                try:
                    name = flow["name"]
                    categories = list(flow.get("categories", []))
                    unit = flow.get("unit", "")
                except Exception:
                    name = str(flow)
                    categories = []
                    unit = ""
                rows.append({
                    "flow": name,
                    "categories": categories,
                    "unit": unit,
                    "score": float(score),
                    "fraction": float(score / total) if total else 0.0,
                })
            return rows


def compare_activities(
    activity_names: list,
    method_name: str,
    database: str = "bafu",
    location: str | None = None,
    amount: float = 1.0,
    method_family: str = "EF v3.1",
) -> list:
    """
    Compare multiple background database activities on a single LCIA method.

    activity_names: list of process names to compare (must exist in `database`)
    method_name: substring match against category e.g. "climate change", "acidification"
    database: Brightway database to search (default "bafu")
    location: optional location filter e.g. "RER", "GLO"
    amount: functional unit amount (default 1.0 kg)
    method_family: top-level method family to search within (default "EF v3.1")

    Returns list of {activity, location, score, unit, fraction} sorted by score descending.
    """
    _ensure_project()
    bg_db = bd.Database(database)

    family_methods = [m for m in bd.methods if len(m) >= 2 and m[0] == method_family]
    if not family_methods:
        raise ValueError(f"Method family '{method_family}' not found.")
    target = next(
        (m for m in sorted(family_methods, key=lambda m: m[-1])
         if method_name.lower() in " | ".join(m[1:]).lower()),
        None,
    )
    if target is None:
        categories = [" | ".join(m[1:]) for m in family_methods]
        raise ValueError(
            f"No category matching '{method_name}' in '{method_family}'. "
            f"Available: {categories[:10]}"
        )

    rows = []
    for name in activity_names:
        act = next(
            (a for a in bg_db
             if a["name"] == name
             and (location is None or a.get("location") == location)),
            None,
        )
        if act is None:
            rows.append({"activity": name, "location": location or "?", "score": None,
                         "unit": "", "fraction": None, "error": "not found"})
            continue
        lca = bc.LCA({act: amount}, target)
        lca.lci()
        lca.lcia()
        rows.append({
            "activity": act["name"],
            "location": act.get("location", ""),
            "score": float(lca.score),
            "unit": bd.methods[target].get("unit", ""),
            "fraction": None,
        })

    # Compute fractions relative to max score
    valid = [r for r in rows if r["score"] is not None]
    if valid:
        max_score = max(r["score"] for r in valid)
        for r in valid:
            r["fraction"] = float(r["score"] / max_score) if max_score else 0.0

    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    return rows


def list_methods() -> list:
    """Return all LCIA methods registered in the current Brightway project."""
    _ensure_project()
    seen = set()
    results = []
    for m in sorted(bd.methods):
        top = m[0]
        if top not in seen:
            seen.add(top)
            results.append({"name": top, "categories": []})
        results[-1]["categories"].append(m[-1])
    return results


def check_brightway() -> dict:
    """Return Brightway project status."""
    try:
        _ensure_project()
        result = {
            "running": True,
            "engine": "brightway2.5",
            "project": BRIGHTWAY_PROJECT,
            "databases": list(bd.databases),
            "methods": len(list(bd.methods)),
        }
        from .search import get_projection_status

        result["search_database"] = get_projection_status(project=BRIGHTWAY_PROJECT)
        return result
    except Exception as exc:
        return {"running": False, "error": str(exc)}
