"""
scripts/setup_databases.py — First-run Brightway 2.5 database setup.

Installs Brightway's default biosphere3 database and built-in LCIA methods
using bw2io.bw2setup().

Run once before starting the server:
    python scripts/setup_databases.py

Idempotent — safe to re-run; skips steps already completed.
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Must be set before bw2data is imported; directory must exist
if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = ROOT / "brightway_data"
    _bw_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)


def _patch_bw2io_reformat_cfs():
    """bw2io 0.9.x returns list keys; bw2data 4.x needs tuples. Patch it."""
    from bw2io.importers import base_lcia

    def _reformat_cfs(self, ds):
        return [(tuple(obj["input"]), obj["amount"]) for obj in ds]

    base_lcia.LCIAImporter._reformat_cfs = _reformat_cfs


def setup():
    import bw2data as bd
    import bw2io

    project = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
    bd.projects.set_current(project)
    print(f"Brightway project : {project}")
    print(f"Data directory    : {bd.projects.dir}")

    _patch_bw2io_reformat_cfs()

    if "biosphere3" not in bd.databases:
        print("Creating default biosphere")
        bw2io.create_default_biosphere3()
    else:
        print("biosphere3 already present — skipping.")

    if not list(bd.methods):
        print("Creating default LCIA methods")
        bw2io.create_default_lcia_methods()
        print("Creating core data migrations")
        bw2io.create_core_migrations()
    else:
        print(f"LCIA methods already present ({len(list(bd.methods))}) — skipping.")

    print("Building searchable SQLite projection")
    from lca_search import build_search_database

    build_search_database(project=project)
    print("Setup complete.")


if __name__ == "__main__":
    setup()
