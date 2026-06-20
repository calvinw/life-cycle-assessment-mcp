"""
scripts/setup_databases.py — First-run Brightway 2.5 database setup.

Creates the lca_biosphere database and LCIA methods from JSON files in
data/lcia/. These files can also be distributed as GitHub release assets
and downloaded here before import.

Run once before starting the server:
    python scripts/setup_databases.py

Idempotent — safe to re-run; skips steps already completed.
"""

import os
import json
import pathlib
import sys

DATA_DIR = pathlib.Path(__file__).parent.parent / "data" / "lcia"
BIOSPHERE_DB = "lca_biosphere"


def setup():
    import bw2data as bd

    project = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
    bd.projects.set_current(project)
    print(f"Brightway project : {project}")
    print(f"Data directory    : {bd.projects.dir}")

    _setup_biosphere(bd)
    _setup_lcia_methods(bd)
    print("Setup complete.")


def _setup_biosphere(bd):
    if BIOSPHERE_DB in bd.databases:
        print(f"  Biosphere '{BIOSPHERE_DB}' already exists — skipping.")
        return

    path = DATA_DIR / "biosphere_flows.json"
    if not path.exists():
        print(f"  ERROR: {path} not found.", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(path.read_text())
    data = {}
    for f in raw:
        key = (BIOSPHERE_DB, f["key"])
        data[key] = {
            "name": f["name"],
            "categories": tuple(f["categories"]),
            "unit": f.get("unit", "kg"),
            "type": f.get("type", "emission"),
            "code": f["key"],
            "database": BIOSPHERE_DB,
        }

    db = bd.Database(BIOSPHERE_DB)
    db.register()
    db.write(data)
    print(f"  Created '{BIOSPHERE_DB}': {len(data)} flows.")


def _setup_lcia_methods(bd):
    for path in sorted(DATA_DIR.glob("method_*.json")):
        data = json.loads(path.read_text())
        method_name = data["name"]

        for cat in data["categories"]:
            method_tuple = (method_name, cat["name"])
            if method_tuple in bd.methods:
                print(f"  Method {method_tuple} already exists — skipping.")
                continue

            cfs = []
            for entry in cat["flows"]:
                flow_key_code = f"{entry['name']}|{entry['compartment']}"
                flow_key = (BIOSPHERE_DB, flow_key_code)
                try:
                    bd.get_activity(flow_key)
                    cfs.append((flow_key, float(entry["cf"])))
                except Exception:
                    pass

            method = bd.Method(method_tuple)
            method.register(
                unit=cat["unit"],
                description=data.get("source", ""),
            )
            method.write(cfs)
            print(f"  Created {method_tuple}: {len(cfs)} CFs.")


if __name__ == "__main__":
    setup()
