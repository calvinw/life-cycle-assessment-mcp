"""Format dispatch for PRISM interchange exports."""

from __future__ import annotations

from typing import Any

from .archive import MAX_PACKAGE_BYTES
from .errors import InterchangeError
from .ecospold2 import export_ecospold2
from .ilcd_export import export_ilcd
from .openlca import export_openlca
from .simapro import export_simapro
from .tidas_export import export_tidas

EXPORT_FORMATS = {
    "openlca-json-ld": export_openlca,
    "ilcd-xml": export_ilcd,
    "tidas-json": export_tidas,
    "ecospold2": export_ecospold2,
    "simapro-csv": export_simapro,
}


def export_interchange(
    format_name: str,
    bundle: dict[str, Any],
    model_id: str | None = None,
) -> bytes:
    """Validate and dispatch a PRISM export to the selected serializer."""
    serializer = EXPORT_FORMATS.get(format_name)
    if serializer is None:
        raise InterchangeError(
            "UNSUPPORTED_EXPORT_FORMAT",
            "Export format must be 'openlca-json-ld', 'ilcd-xml', 'tidas-json', 'ecospold2', or 'simapro-csv'.",
            details={"format": format_name},
            status_code=400,
        )
    if model_id is not None and not isinstance(model_id, str):
        raise InterchangeError(
            "INVALID_EXPORT_MODEL",
            "'model_id' must be a UUID string when provided.",
            details={"field": "model_id"},
            status_code=400,
        )
    package = serializer(bundle, model_id)
    if len(package) > MAX_PACKAGE_BYTES:
        raise InterchangeError(
            "EXPORTED_PACKAGE_TOO_LARGE",
            "The generated package exceeds the 25 MB limit.",
            details={"compressed_bytes": len(package), "limit_bytes": MAX_PACKAGE_BYTES},
            status_code=413,
        )
    return package
