"""
scripts/setup_databases.py — First-run Brightway 2.5 database setup.

Downloads the openLCA LCIA Methods 2.8.0 package from the GitHub release,
imports ~60,000 FEDEFL biosphere flows and 45 LCIA methods into Brightway.

Run once before starting the server:
    python scripts/setup_databases.py

Idempotent — safe to re-run; skips steps already completed.
"""

import os
import json
import pathlib
import sys
import tempfile
import zipfile
import urllib.request

# Must be set before bw2data is imported; directory must exist
if "BRIGHTWAY2_DIR" not in os.environ:
    _bw_dir = pathlib.Path(__file__).parent.parent / "brightway_data"
    _bw_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(_bw_dir)

BIOSPHERE_DB = "lca_biosphere"
RELEASE_URL = (
    "https://github.com/calvinw/life-cycle-assessment-mcp"
    "/releases/download/lca-data-v1"
    "/openLCA.LCIA.Methods.2.8.0.2025-12-15.zip"
)
ZIP_NAME = "openLCA.LCIA.Methods.2.8.0.2025-12-15.zip"


def _download_zip(dest: pathlib.Path):
    if dest.exists():
        print(f"  Using cached {dest.name}")
        return
    print(f"  Downloading {ZIP_NAME} from GitHub release (~158 MB)...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(RELEASE_URL, dest)
    print(f"  Downloaded to {dest}")


def _parse_compartment(category: str) -> str:
    """Map openLCA category string to a simple compartment name."""
    cat = category.lower()
    if "air" in cat:
        return "air"
    if "water" in cat or "freshwater" in cat or "ocean" in cat:
        return "water"
    if "soil" in cat or "ground" in cat or "agricultural" in cat:
        return "ground"
    if "resource" in cat:
        return "resource"
    return "other"


def _parse_unit(flow: dict) -> str:
    for fp in flow.get("flowProperties", []):
        if fp.get("isRefFlowProperty"):
            return fp.get("flowProperty", {}).get("refUnit", "kg")
    return "kg"


def _setup_biosphere(bd, zip_path: pathlib.Path):
    if BIOSPHERE_DB in bd.databases:
        print(f"  Biosphere '{BIOSPHERE_DB}' already exists — skipping.")
        return

    print(f"  Importing biosphere flows from {zip_path.name}...")
    data = {}
    count = 0

    with zipfile.ZipFile(zip_path) as zf:
        flow_names = [n for n in zf.namelist() if n.startswith("flows/") and n.endswith(".json")]
        for name in flow_names:
            flow = json.loads(zf.read(name))
            if flow.get("flowType") != "ELEMENTARY_FLOW":
                continue
            uuid = flow["@id"]
            category_str = flow.get("category", "")
            cats = [c.strip() for c in category_str.split("/") if c.strip()]
            compartment = _parse_compartment(category_str)
            unit = _parse_unit(flow)
            flow_type = "resource" if "resource" in category_str.lower() else "emission"

            key = (BIOSPHERE_DB, uuid)
            data[key] = {
                "name": flow["name"],
                "categories": tuple(cats),
                "unit": unit,
                "type": flow_type,
                "code": uuid,
                "database": BIOSPHERE_DB,
                # Store simple compartment for fast lookup in lca_engine
                "compartment": compartment,
            }
            count += 1

    db = bd.Database(BIOSPHERE_DB)
    db.register()
    db.write(data)
    print(f"  Created '{BIOSPHERE_DB}': {count} elementary flows.")


def _setup_lcia_methods(bd, zip_path: pathlib.Path):
    from bw2io.importers.json_ld_lcia import JSONLDLCIAImporter

    # Check if any methods already exist
    existing = [m for m in bd.methods if len(m) >= 1]
    if existing:
        print(f"  LCIA methods already exist ({len(existing)} categories) — skipping.")
        return

    print("  Importing LCIA methods from openLCA JSON-LD package...")
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"  Extracting zip...")
        with zipfile.ZipFile(zip_path) as zf:
            # Only extract what JSONLDLCIAImporter needs
            for member in zf.namelist():
                if any(member.startswith(p) for p in ("flows/", "lcia_methods/", "lcia_categories/")):
                    zf.extract(member, tmpdir)

        print("  Running JSONLDLCIAImporter...")
        importer = JSONLDLCIAImporter(tmpdir)
        # Patch any categories missing impactFactors (empty categories in the package)
        for cat in importer.data.get("lcia_categories", {}).values():
            cat.setdefault("impactFactors", [])
        # Apply strategies individually — skip normalize_units which chokes on
        # openLCA's list-typed parameters field
        from bw2io.strategies import (
            json_ld_lcia_add_method_metadata,
            json_ld_lcia_convert_to_list,
            json_ld_lcia_set_method_metadata,
            json_ld_lcia_reformat_cfs_as_exchanges,
        )
        for strategy in [
            json_ld_lcia_add_method_metadata,
            json_ld_lcia_convert_to_list,
            json_ld_lcia_set_method_metadata,
            json_ld_lcia_reformat_cfs_as_exchanges,
        ]:
            importer.data = strategy(importer.data)
        importer.match_biosphere_by_id(BIOSPHERE_DB)

        # Count matched vs unmatched
        total_cfs = sum(len(m.get("exchanges", [])) for m in importer.data)
        matched = sum(
            1 for m in importer.data
            for cf in m.get("exchanges", [])
            if "input" in cf
        )
        print(f"  Matched {matched}/{total_cfs} characterization factors.")
        importer.write_methods()
        print(f"  Imported {len(importer.data)} LCIA impact categories.")


def setup():
    import bw2data as bd

    project = os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
    bd.projects.set_current(project)
    print(f"Brightway project : {project}")
    print(f"Data directory    : {bd.projects.dir}")

    # Use cached zip in data/lcia/ if present, otherwise download
    data_dir = pathlib.Path(__file__).parent.parent / "data" / "lcia"
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / ZIP_NAME

    _download_zip(zip_path)
    _setup_biosphere(bd, zip_path)
    _setup_lcia_methods(bd, zip_path)
    print("Setup complete.")


if __name__ == "__main__":
    setup()
