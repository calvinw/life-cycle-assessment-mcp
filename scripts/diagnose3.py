import os, pathlib
os.environ.setdefault("BRIGHTWAY2_DIR", str(pathlib.Path(__file__).parent.parent / "brightway_data"))
import bw2data as bd
bd.projects.set_current("lca_server")

BIOSPHERE_DB = "lca_biosphere"

# Build id → flow map
id_to_flow = {f.id: f for f in bd.Database(BIOSPHERE_DB)}

# Get all N2O air flow IDs that are in the TRACI GWP CF table
traci_gwp_ids = set()
for m in bd.methods:
    if m[0] == "TRACI 2.2" and "Global warming" in m[-1]:
        traci_gwp_ids = {nid for nid, _ in bd.Method(m).load()}

print("=== All Dinitrogen monoxide air flows — in CF table? ===")
for f in bd.Database(BIOSPHERE_DB):
    if f.get("name", "").lower() == "dinitrogen monoxide" and f.get("compartment") == "air":
        in_cf = f.id in traci_gwp_ids
        print(f"  id={f.id}  cats={f.get('categories')}  in_TRACI_GWP={in_cf}")

print()
print("=== All Ammonia air flows — in TRACI eutrophication marine CF table? ===")
traci_eut_ids = set()
for m in bd.methods:
    if m[0] == "TRACI 2.2" and "marine" in m[-1].lower():
        traci_eut_ids = {nid for nid, _ in bd.Method(m).load()}

for f in bd.Database(BIOSPHERE_DB):
    if f.get("name", "").lower() == "ammonia" and f.get("compartment") == "air":
        in_cf = f.id in traci_eut_ids
        print(f"  id={f.id}  cats={f.get('categories')}  in_TRACI_eut_marine={in_cf}")
