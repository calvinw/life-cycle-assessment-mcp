"""Import openLCA JSON-LD packages into a Brightway project."""

from __future__ import annotations

import contextlib
import pathlib
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from typing import Any

import bw2data as bd


@contextlib.contextmanager
def _prepared_jsonld_directory(source: str | pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield an importer-ready directory without modifying the source."""
    source_path = pathlib.Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"JSON-LD source does not exist: {source_path}")

    if source_path.is_dir() and (source_path / "locations").is_dir():
        yield source_path
        return

    with tempfile.TemporaryDirectory(prefix="lca-jsonld-") as temp:
        prepared = pathlib.Path(temp)
        if source_path.is_dir():
            shutil.copytree(source_path, prepared, dirs_exist_ok=True)
        elif zipfile.is_zipfile(source_path):
            with zipfile.ZipFile(source_path) as archive:
                root = prepared.resolve()
                for member in archive.infolist():
                    destination = (prepared / member.filename).resolve()
                    if not destination.is_relative_to(root):
                        raise ValueError(
                            f"Unsafe path in JSON-LD archive: {member.filename}"
                        )
                archive.extractall(prepared)
        else:
            raise ValueError(
                f"JSON-LD source must be a directory or ZIP archive: {source_path}"
            )

        # bw2io's JSON-LD extractor requires this folder even when it is empty.
        (prepared / "locations").mkdir(exist_ok=True)
        yield prepared


def import_jsonld(
    source: str | pathlib.Path,
    database: str,
    project: str,
    *,
    replace_project_data: bool = False,
) -> dict[str, Any]:
    """Import inventory and LCIA data from an openLCA JSON-LD package.

    ``BRIGHTWAY2_DIR`` must be configured before importing :mod:`lca_core` if
    the caller needs a non-default Brightway data directory. Existing project
    data is preserved unless ``replace_project_data`` is explicitly enabled.
    """
    from bw2io.importers.json_ld import JSONLDImporter
    from bw2io.importers.json_ld_lcia import JSONLDLCIAImporter

    bd.projects.set_current(project)
    if replace_project_data:
        for name in list(bd.databases):
            del bd.databases[name]
        for method in list(bd.methods):
            del bd.methods[method]
    elif database in bd.databases:
        raise ValueError(
            f"Database '{database}' already exists in Brightway project '{project}'"
        )

    with _prepared_jsonld_directory(source) as directory:
        inventory = JSONLDImporter(str(directory), database)
        inventory.apply_strategies(no_warning=True)
        inventory.statistics()
        inventory.write_separate_biosphere_database()
        inventory.write_database()

        methods = JSONLDLCIAImporter(str(directory))
        methods.apply_strategies()
        methods.match_biosphere_by_id(f"{database} biosphere")
        methods.statistics()
        methods.write_methods()

    return {
        "project": project,
        "database": database,
        "biosphere_database": f"{database} biosphere",
        "activities": len(bd.Database(database)),
        "methods": len(list(bd.methods)),
    }
