#!/usr/bin/env python3
"""Install or refresh the bundled tiny mock background database."""

import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("BRIGHTWAY2_DIR", str(ROOT / "brightway_data"))
sys.path.insert(0, str(ROOT))

import bw2data as bd

from lca_core.engine import BIOSPHERE_DB, BRIGHTWAY_PROJECT, _ensure_databases
from lca_core.mock_database import ensure_mock_background_database


def main() -> None:
    # This also installs the common biosphere/method data when needed.
    _ensure_databases()
    bd.projects.set_current(BRIGHTWAY_PROJECT)
    result = ensure_mock_background_database(bd, biosphere_database=BIOSPHERE_DB)
    action = "installed" if result["changed"] else "already current"
    print(
        f"{result['database']}: {action}; "
        f"{result['activities']} activities; source {result['source_sha256'][:12]}"
    )


if __name__ == "__main__":
    main()
