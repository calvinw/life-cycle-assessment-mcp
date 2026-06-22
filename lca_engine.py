"""
lca_engine.py — Brightway 2.5 LCA engine.

Accepts a recipe card as a YAML string.
Returns a structured dict with LCI totals, LCIA scores, and scaling vector.
No external server required — all computation runs in-process via Brightway.

Run scripts/setup_databases.py once before using this module.
"""

import os
import pathlib

# Must be set before bw2data is imported; directory must exist
if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = pathlib.Path(__file__).parent / "brightway_data"
    _bw_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

import yaml
import numpy as np
import bw2data as bd
import bw2calc as bc

BRIGHTWAY_PROJECT = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
BIOSPHERE_DB = "biosphere3"
FOREGROUND_DB = "foreground"

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
    bd.projects.set_current(BRIGHTWAY_PROJECT)


def _load_spec(recipe_card_yaml: str) -> dict:
    text = recipe_card_yaml.strip()
    if text.startswith("---"):
        _, fm, _ = text.split("---", 2)
        return yaml.safe_load(fm)
    return yaml.safe_load(text)


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


def run_analysis(recipe_card_yaml: str) -> dict:
    _ensure_project()
    spec = _load_spec(recipe_card_yaml)

    # Rebuild foreground database fresh each run
    if FOREGROUND_DB in bd.databases:
        del bd.databases[FOREGROUND_DB]
    fg = bd.Database(FOREGROUND_DB)
    fg.register()

    # Pass 1 — create all activities so we can resolve technosphere links
    activities: dict = {}
    product_to_activity: dict = {}

    for proc in spec["processes"]:
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

    # Pass 2 — add exchanges
    for proc in spec["processes"]:
        act = activities[proc["name"]]
        ref = proc["reference_output"]

        act.new_exchange(
            input=act,
            amount=float(ref["amount"]),
            type="production",
        ).save()

        for inp in proc.get("inputs", []):
            provider = product_to_activity.get(inp["flow"])
            if provider is None:
                raise ValueError(
                    f"Input flow '{inp['flow']}' in process '{proc['name']}' "
                    f"has no provider in this recipe card."
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
                    f"Check the flow name and compartment in your recipe card."
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
                    f"Check the flow name and compartment in your recipe card."
                )
            act.new_exchange(
                input=flow,
                amount=float(res["amount"]),
                type="biosphere",
            ).save()

    # Identify reference activity and functional unit amount
    ref_proc_name = spec["reference_process"]
    ref_act = activities[ref_proc_name]
    fu_amount = float(spec["functional_unit"]["amount"])

    # Find all LCIA categories for the requested method
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

    # Run LCA — compute inventory once, switch characterization per category
    lca = bc.LCA(demand={ref_act: fu_amount}, method=method_tuples[0])
    lca.lci(factorize=True)

    # Scaling vector (one entry per foreground process)
    scaling_vector: dict = {}
    act_dict = lca.dicts.activity if hasattr(lca, "dicts") else lca.activity_dict

    for act_name, act in activities.items():
        node_id = act.id if hasattr(lca, "dicts") else act.key
        idx = act_dict.get(node_id)
        if idx is not None:
            scaling_vector[act_name] = float(lca.supply_array[idx])

    # LCI totals — sum inventory across all activities in the system
    lci: dict = {}
    total_inv = np.array(lca.inventory.sum(axis=1)).flatten()
    bio_dict = lca.dicts.biosphere if hasattr(lca, "dicts") else lca.biosphere_dict
    bio_db = bd.Database(BIOSPHERE_DB)

    for flow in bio_db:
        node_id = flow.id if hasattr(lca, "dicts") else flow.key
        idx = bio_dict.get(node_id)
        if idx is not None and idx < len(total_inv):
            amount = float(total_inv[idx])
            if abs(amount) > 1e-15:
                flow_type = flow.get("type", "emission")
                lci[flow["name"]] = {
                    "amount": amount,
                    "unit": flow.get("unit", "kg"),
                    "type": flow_type,
                }

    # LCIA scores — one per impact category
    lca.lcia()
    lcia_results: dict = {}
    lcia_results[method_tuples[0][-1]] = {
        "score": float(lca.score),
        "unit": bd.methods[method_tuples[0]].get("unit", ""),
    }
    for method_tuple in method_tuples[1:]:
        lca.switch_method(method_tuple)
        lca.lcia()
        lcia_results[method_tuple[-1]] = {
            "score": float(lca.score),
            "unit": bd.methods[method_tuple].get("unit", ""),
        }

    fu_spec = spec["functional_unit"]
    return {
        "name": spec.get("name", ""),
        "method": method_name,
        "functional_unit": (
            f"{fu_amount} {fu_spec['unit']} — {fu_spec['description']}"
        ),
        "lci": lci,
        "lcia": lcia_results,
        "scaling_vector": scaling_vector,
    }


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
        return {
            "running": True,
            "engine": "brightway2.5",
            "project": BRIGHTWAY_PROJECT,
            "databases": list(bd.databases),
            "methods": len(list(bd.methods)),
        }
    except Exception as exc:
        return {"running": False, "error": str(exc)}
