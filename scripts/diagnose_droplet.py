"""
scripts/diagnose_droplet.py — Check N2O/Ammonia LCIA matching on the droplet.

Run inside the Docker container:
    python3 scripts/diagnose_droplet.py
"""

import os
import pathlib

if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = pathlib.Path(__file__).parent.parent / "brightway_data"
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

import bw2data as bd

bd.projects.set_current("lca_server")

BIOSPHERE_DB = "lca_biosphere"

print(f"Biosphere flows: {bd.databases['lca_biosphere'].get('number')}")
print(f"Methods: {len(list(bd.methods))}")
print()

id_to_flow = {flow.id: flow for flow in bd.Database(BIOSPHERE_DB)}

# Show what _FLOW_INDEX would pick for N2O and Ammonia
flow_index = {}
for flow in bd.Database(BIOSPHERE_DB):
    name_key = flow.get("name", "").lower()
    compartment = flow.get("compartment", "")
    flow_index[(name_key, compartment)] = flow.key

for label, key in [("dinitrogen monoxide", "air"), ("ammonia", "air")]:
    fkey = flow_index.get((label, key))
    if fkey:
        f = bd.get_activity(fkey)
        print(f"Index winner for ({label!r}, {key!r}):")
        print(f"  key={fkey}  id={f.id}  cats={f.get('categories')}")
    else:
        print(f"Index winner for ({label!r}, {key!r}): NOT FOUND")
print()

# Check TRACI 2.2 Global warming CFs for N2O
print("=== TRACI 2.2 Global warming — N2O CFs ===")
for m in bd.methods:
    if m[0] == "TRACI 2.2" and "Global warming" in m[-1]:
        cfs = bd.Method(m).load()
        matched = [(nid, val) for nid, val in cfs if nid in id_to_flow]
        unmatched = [nid for nid, _ in cfs if nid not in id_to_flow]
        n2o_cfs = [(nid, val) for nid, val in matched if "dinitrogen" in id_to_flow[nid].get("name", "").lower()]
        print(f"  Total CFs: {len(cfs)}  Unmatched: {len(unmatched)}")
        for nid, val in n2o_cfs:
            f = id_to_flow[nid]
            print(f"  id={nid}  key={f.key}  cats={f.get('categories')}  CF={val}")
        if not n2o_cfs:
            print("  NO N2O CFs FOUND")
print()

# Check TRACI 2.2 eutrophication CFs for Ammonia
print("=== TRACI 2.2 Eutrophication — Ammonia CFs ===")
for m in bd.methods:
    if m[0] == "TRACI 2.2" and "eutrophication" in m[-1].lower():
        cfs = bd.Method(m).load()
        nh3_cfs = [(nid, val) for nid, val in cfs if nid in id_to_flow and id_to_flow[nid].get("name", "").lower() == "ammonia"]
        print(f"  {m[-1]}: {len(nh3_cfs)} Ammonia CFs")
        for nid, val in nh3_cfs:
            f = id_to_flow[nid]
            print(f"    id={nid}  cats={f.get('categories')}  CF={val}")
