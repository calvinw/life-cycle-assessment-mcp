"""Shared safety checks for untrusted interchange ZIP packages."""

from __future__ import annotations

import io
import posixpath
import stat
import zipfile

from .errors import InterchangeError

MAX_PACKAGE_BYTES = 25 * 1024 * 1024
MAX_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_ENTRIES = 5_000


def write_deterministic_zip(entries: dict[str, bytes]) -> bytes:
    """Return a ZIP whose bytes are stable for the same named entries."""
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])
    return output.getvalue()


def open_safe_zip(package: bytes) -> zipfile.ZipFile:
    """Open *package* after applying the format-independent ZIP limits."""
    if len(package) > MAX_PACKAGE_BYTES:
        raise InterchangeError(
            "PACKAGE_TOO_LARGE",
            "The compressed package exceeds the 25 MB limit.",
            details={"compressed_bytes": len(package), "limit_bytes": MAX_PACKAGE_BYTES},
            status_code=413,
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(package), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise InterchangeError(
            "INVALID_ZIP", "The uploaded file is not a valid ZIP package.", status_code=400
        ) from exc

    try:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise InterchangeError(
                "TOO_MANY_ARCHIVE_ENTRIES",
                "The package contains too many files.",
                details={"entries": len(infos), "limit": MAX_ENTRIES},
                status_code=413,
            )
        expanded = 0
        for info in infos:
            _validate_member(info)
            expanded += info.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise InterchangeError(
                    "EXPANDED_PACKAGE_TOO_LARGE",
                    "The expanded package exceeds the 250 MB limit.",
                    details={
                        "expanded_bytes": expanded,
                        "limit_bytes": MAX_EXPANDED_BYTES,
                    },
                    status_code=413,
                )
    except Exception:
        archive.close()
        raise
    return archive


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    normalized = posixpath.normpath(name)
    mode = info.external_attr >> 16
    if (
        name.startswith(("/", "\\"))
        or normalized == ".."
        or normalized.startswith("../")
        or "\\" in name
    ):
        raise InterchangeError(
            "UNSAFE_ARCHIVE_PATH",
            f"Unsafe ZIP entry '{name}'.",
            details={"path": name},
            status_code=400,
        )
    if stat.S_ISLNK(mode):
        raise InterchangeError(
            "ARCHIVE_SYMLINK",
            f"ZIP entry '{name}' is a symbolic link.",
            details={"path": name},
            status_code=400,
        )
