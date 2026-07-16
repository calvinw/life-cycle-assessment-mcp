"""
lca_engine.py — Brightway 2.5 LCA engine.

Accepts a product graph as a YAML string.
Returns a structured dict with LCI totals, LCIA scores, and scaling vector.
No external server required — all computation runs in-process via Brightway.

Run scripts/setup_databases.py once before using this module.
"""

import os
import pathlib
import tarfile
import threading
import urllib.request

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

# URL of the pre-built Brightway database tarball on GitHub Releases.
# To update: build a new tarball (see docs/bafu_database_setup.md) and bump this URL.
TARBALL_URL = (
    "https://github.com/calvinw/life-cycle-assessment-mcp"
    "/releases/download/lca-data-v2/brightway_bafu_v1.tar.gz"
)

_db_lock = threading.Lock()
_startup_databases_ready = False


def _ensure_search_projection():
    """Build the disposable search database when it is missing or stale."""
    from lca_search import build_search_database, get_projection_status

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


def _build_foreground_db(spec: dict) -> tuple[dict, dict]:
    """Build (or rebuild) the foreground database from a parsed spec.

    Returns (activities, product_to_activity) dicts so callers can
    resolve the reference process without re-parsing the spec.
    """
    if FOREGROUND_DB in bd.databases:
        del bd.databases[FOREGROUND_DB]
    fg = bd.Database(FOREGROUND_DB)
    fg.register()

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

    for proc in spec["processes"]:
        act = activities[proc["name"]]
        ref = proc["reference_output"]

        act.new_exchange(
            input=act,
            amount=float(ref["amount"]),
            type="production",
        ).save()

        for inp in proc.get("inputs", []):
            db_name = inp.get("database")
            if db_name:
                bg_db = bd.Database(db_name)
                location = inp.get("location")
                provider = next(
                    (a for a in bg_db
                     if a["name"] == inp["flow"]
                     and (location is None or a.get("location") == location)),
                    None,
                )
                if provider is None:
                    raise ValueError(
                        f"Background flow '{inp['flow']}' [{location}] not found "
                        f"in database '{db_name}'."
                    )
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

    return activities, product_to_activity


def run_analysis(product_graph_yaml: str) -> dict:
    _ensure_project()
    spec = _load_spec(product_graph_yaml)

    activities, _ = _build_foreground_db(spec)

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

    key0 = " | ".join(method_tuples[0][1:])
    lcia_results[key0] = {
        "score": float(lca.score),
        "unit": bd.methods[method_tuples[0]].get("unit", ""),
    }

    for method_tuple in method_tuples[1:]:
        lca.switch_method(method_tuple)
        lca.lcia()
        key = " | ".join(method_tuple[1:])
        lcia_results[key] = {
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


def get_contributions(product_graph_yaml: str, method_name: str, top_n: int = 10) -> dict:
    """
    Run contribution analysis for a single named impact category.

    Runs a fresh LCA and returns the top processes driving impact for the
    specified category, ranked by absolute score.

    method_name must substring-match a key in the LCIA results
    (e.g. "climate change", "acidification", "water use").
    Returns {method, score, unit, processes: [{activity, location, score, fraction}]}.
    """
    import bw2analyzer as ba
    _ensure_project()

    spec = _load_spec(product_graph_yaml)
    method_name_full = spec["lcia"]["method_name"]
    method_tuples = sorted(
        [m for m in bd.methods if len(m) >= 2 and m[0] == method_name_full],
        key=lambda m: m[-1],
    )
    if not method_tuples:
        raise ValueError(f"LCIA method '{method_name_full}' not found.")

    target = next(
        (m for m in method_tuples if method_name.lower() in " | ".join(m[1:]).lower()),
        None,
    )
    if target is None:
        available = [" | ".join(m[1:]) for m in method_tuples]
        raise ValueError(
            f"Method '{method_name}' not found. Available: {available}"
        )

    activities, _ = _build_foreground_db(spec)

    ref_proc_name = spec["reference_process"]
    ref_act = activities.get(ref_proc_name)
    if ref_act is None:
        raise ValueError(f"Reference process '{ref_proc_name}' not found.")

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
    from lca_search import query_search_database

    return query_search_database(sql, limit=limit, project=BRIGHTWAY_PROJECT)


def get_database_schema() -> dict:
    """Return the schema and freshness of the searchable projection."""
    _ensure_project()
    from lca_search import get_search_schema

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
    from lca_search import search_activities

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
    import bw2analyzer as ba
    _ensure_project()

    spec = _load_spec(product_graph_yaml)
    method_name_full = spec["lcia"]["method_name"]
    method_tuples = sorted(
        [m for m in bd.methods if len(m) >= 2 and m[0] == method_name_full],
        key=lambda m: m[-1],
    )
    target = next(
        (m for m in method_tuples if method_name.lower() in " | ".join(m[1:]).lower()),
        None,
    )
    if target is None:
        available = [" | ".join(m[1:]) for m in method_tuples]
        raise ValueError(f"Method '{method_name}' not found. Available: {available}")

    activities, _ = _build_foreground_db(spec)
    ref_act = activities.get(spec["reference_process"])
    if ref_act is None:
        raise ValueError(f"Reference process '{spec['reference_process']}' not found.")

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
        from lca_search import get_projection_status

        result["search_database"] = get_projection_status(project=BRIGHTWAY_PROJECT)
        return result
    except Exception as exc:
        return {"running": False, "error": str(exc)}
