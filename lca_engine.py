"""
lca_engine.py — core LCA computation for the Life Cycle Assessment MCP.

Accepts a recipe card as a YAML string and a gdt-server URL.
Returns a structured dict with LCI totals, LCIA scores, and scaling vector.
No file I/O — everything in memory.
"""

import yaml
import numpy as np
from olca_ipc.rest import RestClient
import olca_schema as o


def _load_spec(recipe_card_yaml: str) -> dict:
    text = recipe_card_yaml.strip()
    if text.startswith("---"):
        _, fm, _ = text.split("---", 2)
        return yaml.safe_load(fm)
    return yaml.safe_load(text)


def _build_lcia_flow_map(client: RestClient, method_name: str) -> dict:
    """Return a name→UUID map of flows referenced by the named LCIA method."""
    preferred: dict[str, str] = {}
    try:
        for m_desc in client.get_descriptors(o.ImpactMethod):
            if method_name.strip().lower() not in (m_desc.name or "").strip().lower():
                continue
            method = client.get(o.ImpactMethod, m_desc.id)
            for cat_ref in (method.impact_categories or []):
                cat = client.get(o.ImpactCategory, cat_ref.id)
                for cf in (cat.impact_factors or []):
                    fref = cf.flow
                    if fref and fref.name:
                        key = fref.name.strip().lower()
                        if key not in preferred:
                            preferred[key] = fref.id
    except Exception:
        pass
    return preferred


def _resolve_flow(client: RestClient, name: str, flow_property,
                  lcia_flow_map: dict) -> o.Flow:
    key = name.strip().lower()
    preferred_id = lcia_flow_map.get(key)
    if preferred_id:
        existing = client.get(o.Flow, preferred_id)
        if existing is not None:
            return existing
    try:
        for d in client.get_descriptors(o.Flow):
            if d.name and d.name.strip().lower() == key:
                existing = client.get(o.Flow, d.id)
                if existing is not None:
                    return existing
    except Exception:
        pass
    flow = o.new_elementary_flow(name, flow_property)
    if preferred_id:
        flow.id = preferred_id
    client.put(flow)
    return flow


def _build_model(client: RestClient, spec: dict, lcia_flow_map: dict):
    reg: dict = {}

    for symbol, description in spec["units"].items():
        ug = o.new_unit_group(f"{description} units [{symbol}]", symbol)
        fp = o.new_flow_property(description, ug)
        client.put_all(ug, fp)
        reg[symbol] = fp

    for p in spec["products"]:
        flow = o.new_product(p["name"], reg[p["unit"]])
        client.put(flow)
        reg[p["name"]] = flow

    for ef in spec.get("elementary_flows", {}).get("emissions", []):
        reg[ef["name"]] = _resolve_flow(client, ef["name"], reg[ef["unit"]], lcia_flow_map)
    for ef in spec.get("elementary_flows", {}).get("resources", []):
        reg[ef["name"]] = _resolve_flow(client, ef["name"], reg[ef["unit"]], lcia_flow_map)

    for ps in spec["processes"]:
        p = o.new_process(ps["name"])
        ro = ps["reference_output"]
        ref_ex = o.new_output(p, reg[ro["flow"]], ro["amount"])
        ref_ex.is_quantitative_reference = True
        for inp in ps.get("inputs", []):
            o.new_input(p, reg[inp["flow"]], inp["amount"])
        for em in ps.get("emissions", []):
            o.new_output(p, reg[em["flow"]], em["amount"])
        for res in ps.get("resources", []):
            o.new_input(p, reg[res["flow"]], res["amount"])
        client.put(p)
        reg[ps["name"]] = p

    ref_proc = reg[spec["reference_process"]]
    system_ref = client.create_product_system(ref_proc)
    if system_ref is None:
        raise RuntimeError("create_product_system returned None — check gdt-server logs")
    return reg, system_ref


def _build_matrices(spec: dict):
    prod_names = [p["name"] for p in spec["products"]]
    proc_names = [p["name"] for p in spec["processes"]]
    em_names   = [e["name"] for e in spec.get("elementary_flows", {}).get("emissions", [])]
    res_names  = [r["name"] for r in spec.get("elementary_flows", {}).get("resources", [])]

    prod_idx = {n: i for i, n in enumerate(prod_names)}
    ef_idx   = {n: i for i, n in enumerate(em_names + res_names)}

    A = np.zeros((len(prod_names), len(proc_names)))
    B = np.zeros((len(em_names) + len(res_names), len(proc_names)))

    for j, ps in enumerate(spec["processes"]):
        ro = ps["reference_output"]
        if ro["flow"] in prod_idx:
            A[prod_idx[ro["flow"]], j] = ro["amount"]
        for inp in ps.get("inputs", []):
            if inp["flow"] in prod_idx:
                A[prod_idx[inp["flow"]], j] = -inp["amount"]
        for em in ps.get("emissions", []):
            if em["flow"] in ef_idx:
                B[ef_idx[em["flow"]], j] = +em["amount"]
        for res in ps.get("resources", []):
            if res["flow"] in ef_idx:
                B[ef_idx[res["flow"]], j] = -res["amount"]

    return A, B, prod_names, proc_names, em_names, res_names


def _ef_unit(spec: dict, flow_name: str) -> str:
    for ef in spec.get("elementary_flows", {}).get("emissions", []):
        if ef["name"] == flow_name:
            return ef["unit"]
    for ef in spec.get("elementary_flows", {}).get("resources", []):
        if ef["name"] == flow_name:
            return ef["unit"]
    return "?"


def run_analysis(recipe_card_yaml: str,
                 server_url: str = "http://localhost:8080") -> dict:
    """
    Run a full LCA from a recipe card YAML string.

    Returns a dict with:
        name, method, functional_unit, system_id,
        lci  — {flow_name: {amount, unit, type}},
        lcia — {category_name: {score, unit}},
        scaling_vector — {process_name: scale_factor}
    """
    if not server_url.endswith("/"):
        server_url += "/"

    spec        = _load_spec(recipe_card_yaml)
    fu          = spec["functional_unit"]
    method_name = spec.get("lcia", {}).get("method_name", "")

    client = RestClient(server_url)

    lcia_flow_map    = _build_lcia_flow_map(client, method_name) if method_name else {}
    reg, system_ref  = _build_model(client, spec, lcia_flow_map)

    A, B, prod_names, proc_names, em_names, res_names = _build_matrices(spec)
    n_em = len(em_names)

    ref_ps   = next(ps for ps in spec["processes"] if ps["name"] == spec["reference_process"])
    ref_flow = ref_ps["reference_output"]["flow"]
    prod_idx = {n: i for i, n in enumerate(prod_names)}
    f        = np.zeros(len(prod_names))
    f[prod_idx[ref_flow]] = fu["amount"]
    s  = np.linalg.solve(A, f)
    Bs = B @ s

    method_ref = None
    if method_name:
        for d in client.get_descriptors(o.ImpactMethod):
            if d.name and method_name.strip().lower() in d.name.strip().lower():
                method_ref = d.to_ref()
                break

    setup = o.CalculationSetup(
        target=o.Ref(id=system_ref.id),
        amount=fu["amount"],
        impact_method=method_ref,
    )
    result = client.calculate(setup)
    result.wait_until_ready()

    flows        = result.get_total_flows()
    olca_outputs = {f.envi_flow.flow.name: f.amount for f in flows if not f.envi_flow.is_input}
    olca_inputs  = {f.envi_flow.flow.name: f.amount for f in flows if f.envi_flow.is_input}

    lcia_scores: dict = {}
    if method_ref:
        for iv in result.get_total_impacts():
            lcia_scores[iv.impact_category.name] = {
                "score": iv.amount,
                "unit":  iv.impact_category.ref_unit or "",
            }
    result.dispose()

    lci: dict = {}
    for i, name in enumerate(em_names):
        lci[name] = {
            "amount": float(olca_outputs.get(name, Bs[i])),
            "unit":   _ef_unit(spec, name),
            "type":   "emission",
        }
    for i, name in enumerate(res_names):
        lci[name] = {
            "amount": float(olca_inputs.get(name, abs(Bs[n_em + i]))),
            "unit":   _ef_unit(spec, name),
            "type":   "resource",
        }

    return {
        "name":           spec["name"],
        "method":         method_name,
        "functional_unit": f"{fu['amount']} {fu['unit']} — {fu['description']}",
        "system_id":      system_ref.id,
        "lci":            lci,
        "lcia":           lcia_scores,
        "scaling_vector": {proc_names[j]: float(s[j]) for j in range(len(proc_names))},
    }
