"""
lca_engine.py — Brightway 2.5 LCA engine.

Accepts a recipe card as a YAML string.
Returns a structured dict with LCI totals, LCIA scores, and scaling vector.
No external server required — all computation runs in-process via Brightway.

Run scripts/setup_databases.py once before using this module.
"""

import os
import yaml
import numpy as np
import bw2data as bd
import bw2calc as bc

BRIGHTWAY_PROJECT = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
BIOSPHERE_DB = "lca_biosphere"
FOREGROUND_DB = "foreground"


def _ensure_project():
    bd.projects.set_current(BRIGHTWAY_PROJECT)


def _load_spec(recipe_card_yaml: str) -> dict:
    text = recipe_card_yaml.strip()
    if text.startswith("---"):
        _, fm, _ = text.split("---", 2)
        return yaml.safe_load(fm)
    return yaml.safe_load(text)


def _find_biosphere_flow(name: str, compartment: str):
    """Look up a flow in lca_biosphere by FEDEFL name and compartment."""
    key = (BIOSPHERE_DB, f"{name}|{compartment}")
    try:
        return bd.get_activity(key)
    except Exception:
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
                    f"Add it to data/lcia/biosphere_flows.json and re-run setup."
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
                    f"Add it to data/lcia/biosphere_flows.json and re-run setup."
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
                cats = flow.get("categories", [])
                flow_type = (
                    "resource" if any(c in cats for c in ("water", "ground", "raw"))
                    else "emission"
                )
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
