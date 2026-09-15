"""Format detection and dispatch for supported interchange packages."""

from __future__ import annotations

from typing import Any

from .archive import open_safe_zip
from .errors import InterchangeError
from .ilcd import preview_ilcd
from .openlca import OPENLCA_MANIFEST_NAMES, preview_openlca


def preview_interchange(package: bytes) -> dict[str, Any]:
    """Detect a supported ZIP layout and return its PRISM import preview."""
    archive = open_safe_zip(package)
    with archive:
        names = {info.filename for info in archive.infolist()}
    if names & OPENLCA_MANIFEST_NAMES:
        return preview_openlca(package)
    if any(name.startswith("ILCD/") for name in names):
        return preview_ilcd(package)
    raise InterchangeError(
        "UNSUPPORTED_PACKAGE_FORMAT",
        "The ZIP is neither an openLCA JSON-LD nor an ILCD/eILCD package.",
        status_code=400,
    )
