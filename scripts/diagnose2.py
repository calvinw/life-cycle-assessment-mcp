import os, pathlib
os.environ.setdefault("BRIGHTWAY2_DIR", str(pathlib.Path(__file__).parent.parent / "brightway_data"))
import bw2data as bd
bd.projects.set_current("lca_server")

bio = list(bd.Database("lca_biosphere"))
id_to_flow = {f.id: f for f in bio}

# Build flow index (same logic as lca_engine.py)
index = {}
for f in bio:
    index[(f.get("name","").lower(), f.get("compartment",""))] = f

n2o = index.get(("dinitrogen monoxide", "air"))
nh3 = index.get(("ammonia", "air"))
print("N2O index winner:", n2o.get("categories") if n2o else "MISSING", "id=", n2o.id if n2o else "?")
print("NH3 index winner:", nh3.get("categories") if nh3 else "MISSING", "id=", nh3.id if nh3 else "?")

for m in bd.methods:
    if m[0] == "TRACI 2.2" and "Global warming" in m[-1]:
        cfs = dict(bd.Method(m).load())
        print("N2O in TRACI GWP CF table:", n2o.id in cfs if n2o else "N/A", "CF=", cfs.get(n2o.id) if n2o else "?")
        print("Unmatched CFs:", sum(1 for k in cfs if k not in id_to_flow))
