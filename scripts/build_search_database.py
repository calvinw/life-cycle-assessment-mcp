#!/usr/bin/env python3
"""Build the searchable SQLite projection from Brightway databases."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "BRIGHTWAY2_DIR" not in os.environ:
    data_dir = ROOT / "brightway_data"
    data_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(data_dir)

from lca_search import build_search_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        action="append",
        dest="databases",
        help="Brightway database to include; repeat as needed (dependencies are automatic)",
    )
    parser.add_argument("--project", default=os.environ.get("BRIGHTWAY_PROJECT", "lca_server"))
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    build_search_database(
        databases=args.databases,
        output_path=args.output,
        project=args.project,
    )


if __name__ == "__main__":
    main()
