"""Format detection and dispatch for supported interchange packages."""

from __future__ import annotations

from typing import Any

from .archive import open_safe_zip
from .ecospold2 import (
    is_ecospold2_zip,
    looks_like_ecospold2_xml,
    preview_ecospold2,
)
from .errors import InterchangeError
from .ilcd import has_root_level_ilcd_layout, preview_ilcd
from .openlca import OPENLCA_MANIFEST_NAMES, preview_openlca
from .simapro import looks_like_simapro_csv, preview_simapro
from .tidas import is_tidas_package, preview_tidas


def preview_interchange(package: bytes) -> dict[str, Any]:
    """Detect a supported ZIP/XML layout and return its PRISM import preview."""
    if looks_like_ecospold2_xml(package):
        return preview_ecospold2(package)
    if looks_like_simapro_csv(package):
        return preview_simapro(package)
    archive = open_safe_zip(package)
    with archive:
        names = {info.filename for info in archive.infolist()}
    if names & OPENLCA_MANIFEST_NAMES:
        return preview_openlca(package)
    if any(name.startswith("ILCD/") for name in names):
        return preview_ilcd(package)
    # manifest.json (TIDAS) is checked before the root-of-zip ILCD layout
    # signal so a TIDAS package's own root-level dataset folders (.json,
    # not .xml, but checked here defensively) are never misrouted.
    if is_tidas_package(package, names):
        return preview_tidas(package)
    if is_ecospold2_zip(package, names):
        return preview_ecospold2(package)
    if has_root_level_ilcd_layout(names):
        return preview_ilcd(package)
    raise InterchangeError(
        "UNSUPPORTED_PACKAGE_FORMAT",
        "The upload is not an openLCA JSON-LD, ILCD/eILCD, TIDAS JSON, EcoSpold2, or SimaPro CSV package.",
        status_code=400,
    )
