"""
scripts/diagnose_recipe_lcia.py — Diagnose zero LCIA scores for non-TRACI methods.

Run:
    python scripts/diagnose_recipe_lcia.py
"""

import os, pathlib

if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = pathlib.Path(__file__).parent.parent / "brightway_data"
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

import bw2data as bd

PROJECT = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
bd.projects.set_current(PROJECT)

print(f"=== Project: {PROJECT} ===")
print(f"Databases: {list(bd.databases)}")
print(f"Total LCIA methods: {len(list(bd.methods))}")
print()

# 1. Find key biosphere3 flows used in the cotton recipe
bio = bd.Database("biosphere3")
TARGET_FLOWS = ["carbon dioxide, fossil", "dinitrogen monoxide", "ammonia", "water"]
print("=== Biosphere3 flows (key, name, categories) ===")
found_flows = {}
for flow in bio:
    name_lc = flow["name"].lower()
    if any(t in name_lc for t in TARGET_FLOWS):
        cats = flow.get("categories", ())
        sub = cats[-1] if len(cats) > 1 else ""
        if "unspecified" in sub.lower() or not sub:
            print(f"  key={flow.key}  name={flow['name']!r}  cats={cats}")
            found_flows[flow["name"].lower()] = flow.key
print()

# 2. Check which methods are available that contain "ReCiPe"
recipe_methods = [m for m in bd.methods if "recipe" in str(m).lower() or "Recipe" in str(m)]
print(f"=== ReCiPe methods found ({len(recipe_methods)}) ===")
for m in recipe_methods[:10]:
    print(f"  {m}")
if len(recipe_methods) > 10:
    print(f"  ... and {len(recipe_methods)-10} more")
print()

# 3. For "ReCiPe 2016 Midpoint (H)", check how many CFs reference our flows
TARGET_METHOD_PREFIX = "ReCiPe 2016 Midpoint (H)"
matching = [m for m in bd.methods if m[0] == TARGET_METHOD_PREFIX]
print(f"=== Methods with m[0] == {TARGET_METHOD_PREFIX!r}: {len(matching)} ===")
for m in matching[:5]:
    print(f"  {m}")
print()

# 4. Print all unique top-level method names
all_tops = sorted({m[0] for m in bd.methods})
print(f"=== All unique method group names ({len(all_tops)}) ===")
for name in all_tops:
    print(f"  {name!r}")
print()

# 5. Check CF structure for TRACI (working reference)
traci_methods = [m for m in bd.methods if "TRACI" in str(m)]
print(f"=== TRACI methods ({len(traci_methods)}) ===")
for m in traci_methods[:5]:
    print(f"  {m}")
if traci_methods:
    sample_traci = traci_methods[0]
    traci_cfs = bd.Method(sample_traci).load()
    print(f"  Total CFs: {len(traci_cfs)}")
    print(f"  Sample entries: {traci_cfs[:3]}")
    # Count hits against our biosphere3 flows regardless of key format
    bio_keys = set(found_flows.values())
    hits = sum(1 for entry in traci_cfs if entry[0] in bio_keys)
    print(f"  CFs matching our biosphere3 flow keys: {hits}")
print()

print("=== Done ===")
