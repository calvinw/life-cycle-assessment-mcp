"""Process-resident cumulative LCIA intensities for background products."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import sqlite3
import threading
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
from scipy.sparse.linalg import splu


CACHE_ENV_VAR = "LCA_BACKGROUND_INTENSITY_CACHE"
CACHE_MODES = {"off", "compare", "on"}
FOREGROUND_DB_PREFIX = "foreground_request_"
LEGACY_FOREGROUND_DB = "foreground"

_logger = logging.getLogger(__name__)
_cache_lock = threading.RLock()
_entries: dict[tuple, "_BackgroundEntry"] = {}
_disabled_reason: str | None = None


class BackgroundIntensityError(RuntimeError):
    """Raised when a background intensity cannot be built safely."""


class BackgroundInvariantError(BackgroundIntensityError):
    """Raised when a background exchange references request foreground state."""


@dataclass
class _BackgroundEntry:
    key: tuple
    database_names: tuple[str, ...]
    lca: Any
    transpose_lu: Any
    current_method: tuple
    y_by_method: dict[tuple, Mapping[int, float]] = field(default_factory=dict)


def configured_mode() -> str:
    value = os.environ.get(CACHE_ENV_VAR, "off").strip().lower()
    if value not in CACHE_MODES:
        _logger.error(
            "Invalid %s=%r; background intensity cache remains off",
            CACHE_ENV_VAR,
            value,
        )
        return "off"
    return value


def effective_mode() -> str:
    if _disabled_reason is not None:
        return "off"
    return configured_mode()


def disable(reason: str) -> None:
    global _disabled_reason
    with _cache_lock:
        _disabled_reason = reason
        _logger.error("Background intensity cache disabled: %s", reason)


def clear_cache() -> None:
    global _disabled_reason
    with _cache_lock:
        _entries.clear()
        _disabled_reason = None


def cache_info() -> dict[str, Any]:
    with _cache_lock:
        return {
            "mode": configured_mode(),
            "effective_mode": effective_mode(),
            "disabled_reason": _disabled_reason,
            "entries": len(_entries),
            "methods": sum(len(entry.y_by_method) for entry in _entries.values()),
            "database_sets": [entry.database_names for entry in _entries.values()],
        }


def database_names_from_spec(spec: dict) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                exchange["database"]
                for process in spec["processes"]
                for exchange in process.get("inputs", [])
                if exchange.get("database")
            }
        )
    )


def _expanded_database_names(bd, database_names: tuple[str, ...]) -> tuple[str, ...]:
    selected = set(database_names)
    pending = list(database_names)
    while pending:
        name = pending.pop()
        if name not in bd.databases:
            raise BackgroundIntensityError(
                f"Background database '{name}' is not installed"
            )
        for dependency in bd.databases[name].get("depends", []):
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return tuple(sorted(selected))


def database_identity(bd, database_names: tuple[str, ...]) -> tuple:
    expanded = _expanded_database_names(bd, database_names)
    identity = []
    for name in expanded:
        metadata = bd.databases[name]
        identity.append(
            (
                name,
                metadata.get("version"),
                metadata.get("source_sha256"),
                metadata.get("mock_source_sha256"),
                metadata.get("mock_schema_version"),
                metadata.get("number"),
                str(metadata.get("modified")),
                str(metadata.get("processed")),
                metadata.get("backend"),
                tuple(sorted(metadata.get("depends", []))),
            )
        )
    return (str(bd.projects.current), database_names, tuple(identity))


def _validate_background_exchanges(bd, database_names: tuple[str, ...]) -> None:
    from .search import get_projection_status

    status = get_projection_status(project=str(bd.projects.current))
    if not status.get("fresh"):
        raise BackgroundIntensityError(
            "Cannot validate INVARIANT B1 because the search projection is not "
            f"fresh: {status.get('reason', 'unknown reason')}"
        )
    placeholders = ", ".join("?" for _ in database_names)
    query = f"""
        SELECT output_database, output_code, input_database, input_code
        FROM exchanges
        WHERE output_database IN ({placeholders})
          AND (
            input_database = ?
            OR input_database GLOB ?
          )
        LIMIT 10
    """
    with sqlite3.connect(status["path"]) as connection:
        offenders = connection.execute(
            query,
            (
                *database_names,
                LEGACY_FOREGROUND_DB,
                f"{FOREGROUND_DB_PREFIX}*",
            ),
        ).fetchall()
    if offenders:
        raise BackgroundInvariantError(
            "INVARIANT B1 violated by background technosphere exchanges: "
            + ", ".join(
                f"({output_database}, {output_code}) -> "
                f"({input_database}, {input_code})"
                for output_database, output_code, input_database, input_code in offenders
            )
        )


def _build_entry(bd, bc, database_names: tuple[str, ...], method: tuple):
    if not database_names:
        raise BackgroundIntensityError("A background database set is required")
    _validate_background_exchanges(
        bd,
        _expanded_database_names(bd, database_names),
    )
    demand = {
        next(iter(bd.Database(database_name))): 1.0
        for database_name in database_names
    }
    if len(demand) != len(database_names):
        raise BackgroundIntensityError(
            f"Could not seed every background database: {database_names}"
        )
    lca = bc.LCA(demand=demand, method=method)
    lca.lci()
    if lca.technosphere_matrix.shape[0] != lca.technosphere_matrix.shape[1]:
        raise BackgroundIntensityError(
            "Background technosphere matrix must be square; got "
            f"{lca.technosphere_matrix.shape}"
        )
    transpose_lu = splu(lca.technosphere_matrix.T.tocsc())
    key = database_identity(bd, database_names)
    return _BackgroundEntry(
        key=key,
        database_names=database_names,
        lca=lca,
        transpose_lu=transpose_lu,
        current_method=method,
    )


def direct_intensities(lca) -> np.ndarray:
    characterized_biosphere = (
        lca.characterization_matrix @ lca.biosphere_matrix
    )
    return np.asarray(characterized_biosphere.sum(axis=0)).ravel()


def get_background_y(
    bd,
    bc,
    database_names: tuple[str, ...],
    method: tuple,
) -> Mapping[int, float]:
    database_names = tuple(sorted(database_names))
    with _cache_lock:
        key = database_identity(bd, database_names)
        entry = _entries.get(key)
        if entry is None:
            for old_key, old_entry in list(_entries.items()):
                if (
                    old_entry.database_names == database_names
                    and old_key[0] == key[0]
                ):
                    del _entries[old_key]
            entry = _build_entry(bd, bc, database_names, method)
            _entries[entry.key] = entry

        cached = entry.y_by_method.get(method)
        if cached is not None:
            return cached
        if entry.current_method != method:
            entry.lca.switch_method(method)
            entry.current_method = method
        entry.lca.lcia()
        direct = direct_intensities(entry.lca)
        cumulative = np.asarray(entry.transpose_lu.solve(direct)).ravel()
        values = MappingProxyType(
            {
                node_id: float(cumulative[index])
                for node_id, index in entry.lca.dicts.product.items()
            }
        )
        entry.y_by_method[method] = values
        return values


def warm(bd, bc, requests: set[tuple[tuple[str, ...], tuple]]) -> None:
    for database_names, method in sorted(
        requests,
        key=lambda item: (item[0], item[1]),
    ):
        get_background_y(bd, bc, database_names, method)


def assemble_request_cumulative_intensities(
    *,
    bd,
    bc,
    lca,
    activities: dict,
    database_names: tuple[str, ...],
    method: tuple,
) -> np.ndarray:
    foreground_activity_ids = {activity.id for activity in activities.values()}
    foreground_activity_columns = np.array(
        sorted(lca.dicts.activity[node_id] for node_id in foreground_activity_ids),
        dtype=int,
    )
    background_activity_columns = np.array(
        sorted(
            index
            for node_id, index in lca.dicts.activity.items()
            if node_id not in foreground_activity_ids
        ),
        dtype=int,
    )

    missing_foreground_products = foreground_activity_ids.difference(
        lca.dicts.product
    )
    if missing_foreground_products:
        raise BackgroundIntensityError(
            "Foreground activities are missing from the product index: "
            + ", ".join(str(node_id) for node_id in sorted(missing_foreground_products))
        )
    foreground_product_rows = [
        lca.dicts.product[node_id] for node_id in foreground_activity_ids
    ]
    foreground_product_ids = set(foreground_activity_ids)
    background_product_rows = []
    background_product_ids = {}
    for node_id, index in lca.dicts.product.items():
        if node_id not in foreground_product_ids:
            background_product_rows.append(index)
            background_product_ids[index] = node_id
    foreground_product_rows = np.array(sorted(foreground_product_rows), dtype=int)
    background_product_rows = np.array(sorted(background_product_rows), dtype=int)

    a_fb = lca.technosphere_matrix[foreground_product_rows, :][
        :, background_activity_columns
    ]
    if a_fb.nnz:
        raise BackgroundInvariantError(
            f"INVARIANT B1 violated: A_FB has {a_fb.nnz} stored entries"
        )

    if database_names:
        cached = get_background_y(bd, bc, database_names, method)
        y_b = np.array(
            [cached[background_product_ids[index]] for index in background_product_rows],
            dtype=float,
        )
    else:
        if len(background_product_rows):
            raise BackgroundIntensityError(
                "The request matrix has background products but the spec names no "
                "background databases"
            )
        y_b = np.array([], dtype=float)

    direct = direct_intensities(lca)
    a_ff = lca.technosphere_matrix[foreground_product_rows, :][
        :, foreground_activity_columns
    ].toarray()
    a_bf = lca.technosphere_matrix[background_product_rows, :][
        :, foreground_activity_columns
    ]
    right_hand_side = direct[foreground_activity_columns] - np.asarray(
        a_bf.T @ y_b
    ).ravel()
    y_f = np.linalg.solve(a_ff.T, right_hand_side)

    cumulative = np.zeros(lca.technosphere_matrix.shape[0], dtype=float)
    cumulative[foreground_product_rows] = y_f
    cumulative[background_product_rows] = y_b
    return cumulative
