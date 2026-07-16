"""Searchable, read-only SQLite projection of Brightway inventory data.

Brightway remains the source of truth. This module builds a disposable SQLite
database with ordinary scalar columns and provides safe read-only query helpers.
It never participates in LCA calculation.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import math
import os
import pathlib
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any


# Match lca_engine.py when this module is used directly by scripts or tests.
if "BRIGHTWAY2_DIR" not in os.environ:
    _default_bw_dir = pathlib.Path(__file__).parent / "brightway_data"
    _default_bw_dir.mkdir(exist_ok=True)
    os.environ["BRIGHTWAY2_DIR"] = str(_default_bw_dir)


SCHEMA_VERSION = "1"
DEFAULT_FILENAME = "search.sqlite3"
EXCLUDED_DATABASES = {"foreground"}
PUBLIC_TABLES = (
    "projection_metadata",
    "activities",
    "activity_categories",
    "activity_classifications",
    "activity_synonyms",
    "exchanges",
    "activities_fts",
)
PUBLIC_VIEWS = ("exchange_details", "process_inputs")


SCHEMA_SQL = """
CREATE TABLE projection_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE activities (
    database TEXT NOT NULL,
    code TEXT NOT NULL,
    brightway_id INTEGER,
    name TEXT NOT NULL,
    reference_product TEXT,
    location TEXT,
    unit TEXT,
    type TEXT,
    categories_text TEXT,
    comment TEXT,
    filename TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extra_json)),
    PRIMARY KEY (database, code)
);

CREATE TABLE activity_categories (
    database TEXT NOT NULL,
    code TEXT NOT NULL,
    position INTEGER NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY (database, code, position),
    FOREIGN KEY (database, code) REFERENCES activities(database, code)
);

CREATE TABLE activity_classifications (
    database TEXT NOT NULL,
    code TEXT NOT NULL,
    system TEXT NOT NULL,
    value TEXT NOT NULL,
    FOREIGN KEY (database, code) REFERENCES activities(database, code)
);

CREATE TABLE activity_synonyms (
    database TEXT NOT NULL,
    code TEXT NOT NULL,
    synonym TEXT NOT NULL,
    FOREIGN KEY (database, code) REFERENCES activities(database, code)
);

CREATE TABLE exchanges (
    id INTEGER PRIMARY KEY,
    brightway_id INTEGER,
    output_database TEXT NOT NULL,
    output_code TEXT NOT NULL,
    input_database TEXT NOT NULL,
    input_code TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    unit TEXT,
    name TEXT,
    reference_product TEXT,
    location TEXT,
    categories_text TEXT,
    uncertainty_type INTEGER,
    loc REAL,
    scale REAL,
    shape REAL,
    minimum REAL,
    maximum REAL,
    negative INTEGER,
    formula TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(extra_json)),
    FOREIGN KEY (output_database, output_code)
        REFERENCES activities(database, code)
);

CREATE INDEX activity_name_nocase ON activities(name COLLATE NOCASE);
CREATE INDEX activity_classification_value
    ON activity_classifications(system, value);
CREATE INDEX activity_synonym_nocase
    ON activity_synonyms(synonym COLLATE NOCASE);
CREATE INDEX exchange_output
    ON exchanges(output_database, output_code, type);
CREATE INDEX exchange_input
    ON exchanges(input_database, input_code, type);
CREATE INDEX exchange_type_unit ON exchanges(type, unit);

CREATE VIRTUAL TABLE activities_fts USING fts5(
    database UNINDEXED,
    code UNINDEXED,
    name,
    reference_product,
    comment,
    categories,
    classifications,
    synonyms,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE VIEW exchange_details AS
SELECT
    e.id,
    e.brightway_id,
    e.output_database,
    e.output_code,
    consumer.name AS consumer_name,
    consumer.reference_product AS consumer_product,
    consumer.location AS consumer_location,
    consumer.unit AS consumer_unit,
    e.input_database,
    e.input_code,
    supplied.name AS input_name,
    supplied.reference_product AS input_product,
    supplied.location AS input_location,
    supplied.unit AS input_reference_unit,
    e.type AS exchange_type,
    e.amount,
    e.unit,
    e.uncertainty_type,
    e.loc,
    e.scale,
    e.shape,
    e.minimum,
    e.maximum,
    e.negative,
    e.formula
FROM exchanges AS e
JOIN activities AS consumer
  ON consumer.database = e.output_database AND consumer.code = e.output_code
LEFT JOIN activities AS supplied
  ON supplied.database = e.input_database AND supplied.code = e.input_code;

CREATE VIEW process_inputs AS
SELECT * FROM exchange_details WHERE exchange_type != 'production';
"""


ACTIVITY_COLUMNS = {
    "database",
    "code",
    "id",
    "name",
    "reference product",
    "product",
    "location",
    "unit",
    "type",
    "categories",
    "comment",
    "filename",
    "classifications",
    "synonyms",
}

EXCHANGE_COLUMNS = {
    "id",
    "input",
    "output",
    "type",
    "amount",
    "unit",
    "name",
    "reference product",
    "product",
    "location",
    "categories",
    "uncertainty type",
    "loc",
    "scale",
    "shape",
    "minimum",
    "maximum",
    "negative",
    "formula",
}


def _import_bw2data():
    import bw2data as bd

    return bd


def _set_project(project: str | None = None):
    bd = _import_bw2data()
    target = project or os.environ.get("BRIGHTWAY_PROJECT", "lca_server")
    bd.projects.set_current(target)
    return bd


def get_search_database_path(project: str | None = None) -> pathlib.Path:
    """Return the projection path for the active (or named) Brightway project."""
    bd = _set_project(project)
    return pathlib.Path(bd.projects.dir) / "search" / DEFAULT_FILENAME


def _json_safe(value: Any, path: str = "value") -> Any:
    """Convert common Brightway values to deterministic JSON-compatible data."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, f"{path}.{key}")
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, f"{path}[]") for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_json_safe(item, f"{path}[]") for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    # NumPy scalar values and similar wrappers expose a scalar .item().
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is not value:
            return _json_safe(scalar, path)
    raise TypeError(f"{path} contains unsupported value {type(value).__name__}")


def _json_text(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _real(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Expected a finite number, got {value!r}")
    return number


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _categories(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _classifications(value: Any) -> list[tuple[str, str]]:
    if not value:
        return []
    result: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        iterable = value.items()
    else:
        iterable = value
    for item in iterable:
        if isinstance(item, Mapping):
            system = item.get("system") or item.get("name") or ""
            classification = item.get("value") or item.get("code") or ""
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            system, classification = item[0], item[1]
        else:
            system, classification = "", item
        result.append((str(system), str(classification)))
    return result


def _synonyms(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return sorted(str(item) for item in value)


def _activity_row(data: Mapping[str, Any]) -> tuple[Any, ...]:
    extra = {key: value for key, value in data.items() if key not in ACTIVITY_COLUMNS}
    categories = _categories(data.get("categories"))
    return (
        str(data["database"]),
        str(data["code"]),
        _integer(data.get("id")),
        str(data.get("name") or ""),
        _text(data.get("reference product", data.get("product"))),
        _text(data.get("location")),
        _text(data.get("unit")),
        _text(data.get("type")),
        "::".join(categories) or None,
        _text(data.get("comment")),
        _text(data.get("filename")),
        _json_text(extra),
    )


def _exchange_row(data: Mapping[str, Any], brightway_id: int | None) -> tuple[Any, ...]:
    extra = {key: value for key, value in data.items() if key not in EXCHANGE_COLUMNS}
    input_key = data.get("input")
    output_key = data.get("output")
    if not isinstance(input_key, (tuple, list)) or len(input_key) != 2:
        raise ValueError(f"Exchange has invalid input key: {input_key!r}")
    if not isinstance(output_key, (tuple, list)) or len(output_key) != 2:
        raise ValueError(f"Exchange has invalid output key: {output_key!r}")
    amount = _real(data.get("amount"))
    if amount is None:
        raise ValueError("Exchange has no amount")
    return (
        _integer(brightway_id),
        str(output_key[0]),
        str(output_key[1]),
        str(input_key[0]),
        str(input_key[1]),
        str(data.get("type") or ""),
        amount,
        _text(data.get("unit")),
        _text(data.get("name")),
        _text(data.get("reference product", data.get("product"))),
        _text(data.get("location")),
        "::".join(_categories(data.get("categories"))) or None,
        _integer(data.get("uncertainty type")),
        _real(data.get("loc")),
        _real(data.get("scale")),
        _real(data.get("shape")),
        _real(data.get("minimum")),
        _real(data.get("maximum")),
        int(bool(data["negative"])) if data.get("negative") is not None else None,
        _text(data.get("formula")),
        _json_text(extra),
    )


def _database_fingerprint(bd, database_names: Sequence[str]) -> list[dict[str, Any]]:
    fields = ("number", "modified", "backend", "depends")
    result = []
    for name in sorted(database_names):
        metadata = bd.databases[name]
        result.append(
            {
                "name": name,
                **{field: _json_safe(metadata.get(field)) for field in fields},
            }
        )
    return result


def _expand_databases(bd, requested: Sequence[str] | None) -> list[str]:
    if requested is None:
        seeds = [name for name in bd.databases if name not in EXCLUDED_DATABASES]
    else:
        seeds = list(dict.fromkeys(requested))
    missing = [name for name in seeds if name not in bd.databases]
    if missing:
        raise ValueError(
            f"Brightway database(s) not found: {missing}. Available: {list(bd.databases)}"
        )

    selected = set(seeds)
    pending = list(seeds)
    while pending:
        name = pending.pop()
        for dependency in bd.databases[name].get("depends", []):
            if dependency not in bd.databases:
                raise ValueError(
                    f"Database '{name}' declares missing dependency '{dependency}'"
                )
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return sorted(selected)


def _create_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.executescript(SCHEMA_SQL)
    except sqlite3.OperationalError as exc:
        if "fts5" in str(exc).lower():
            raise RuntimeError("This SQLite runtime does not include required FTS5 support") from exc
        raise


def _metadata_values(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT key, value FROM projection_metadata").fetchall()
    result = {}
    for key, value in rows:
        try:
            result[key] = json.loads(value)
        except json.JSONDecodeError:
            result[key] = value
    return result


def _validate_projection(
    conn: sqlite3.Connection,
    expected_activities: int,
    expected_exchanges: int,
) -> dict[str, int]:
    activity_count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    exchange_count = conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM activities_fts").fetchone()[0]
    unresolved_outputs = conn.execute(
        """SELECT COUNT(*) FROM exchanges AS e
           LEFT JOIN activities AS a
             ON a.database=e.output_database AND a.code=e.output_code
           WHERE a.code IS NULL"""
    ).fetchone()[0]
    unresolved_inputs = conn.execute(
        """SELECT COUNT(*) FROM exchanges AS e
           LEFT JOIN activities AS a
             ON a.database=e.input_database AND a.code=e.input_code
           WHERE a.code IS NULL"""
    ).fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if activity_count != expected_activities:
        raise RuntimeError(
            f"Projection has {activity_count} activities; expected {expected_activities}"
        )
    if exchange_count != expected_exchanges:
        raise RuntimeError(
            f"Projection has {exchange_count} exchanges; expected {expected_exchanges}"
        )
    if fts_count != activity_count:
        raise RuntimeError(f"FTS has {fts_count} rows; expected {activity_count}")
    if unresolved_outputs:
        raise RuntimeError(f"Projection has {unresolved_outputs} unresolved output keys")
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    return {
        "activity_count": activity_count,
        "exchange_count": exchange_count,
        "unresolved_input_count": unresolved_inputs,
    }


@contextlib.contextmanager
def _exclusive_build_lock(lock_path: pathlib.Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another search database build is already running: {lock_path}") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def build_search_database(
    databases: Sequence[str] | None = None,
    *,
    output_path: str | pathlib.Path | None = None,
    project: str | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    """Build and atomically publish a searchable projection.

    Dependencies of requested databases are included automatically. If
    ``databases`` is omitted, all databases except the generated ``foreground``
    database are included.
    """
    started = time.monotonic()
    bd = _set_project(project)
    project_name = bd.projects.current
    database_names = _expand_databases(bd, databases)
    destination = (
        pathlib.Path(output_path)
        if output_path is not None
        else get_search_database_path(project_name)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    )
    lock_path = destination.with_suffix(destination.suffix + ".lock")

    if progress:
        print(f"Building search projection for: {', '.join(database_names)}")
        print(f"Output: {destination}")

    with _exclusive_build_lock(lock_path):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(temp_path)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = OFF")
            conn.execute("PRAGMA synchronous = OFF")
            conn.execute("PRAGMA temp_store = MEMORY")
            _create_schema(conn)
            conn.execute("BEGIN")

            activity_count = 0
            exchange_count = 0
            exchange_batch: list[tuple[Any, ...]] = []

            for database_name in database_names:
                db = bd.Database(database_name)
                db_activities = 0
                db_exchanges = 0
                for activity in db:
                    data = activity.as_dict()
                    database = str(data["database"])
                    code = str(data["code"])
                    categories = _categories(data.get("categories"))
                    classifications = _classifications(data.get("classifications"))
                    synonyms = _synonyms(data.get("synonyms"))

                    conn.execute(
                        """INSERT INTO activities (
                            database, code, brightway_id, name, reference_product,
                            location, unit, type, categories_text, comment,
                            filename, extra_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        _activity_row(data),
                    )
                    conn.executemany(
                        "INSERT INTO activity_categories VALUES (?, ?, ?, ?)",
                        [
                            (database, code, position, category)
                            for position, category in enumerate(categories)
                        ],
                    )
                    conn.executemany(
                        "INSERT INTO activity_classifications VALUES (?, ?, ?, ?)",
                        [
                            (database, code, system, value)
                            for system, value in classifications
                        ],
                    )
                    conn.executemany(
                        "INSERT INTO activity_synonyms VALUES (?, ?, ?)",
                        [(database, code, synonym) for synonym in synonyms],
                    )
                    conn.execute(
                        "INSERT INTO activities_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            database,
                            code,
                            str(data.get("name") or ""),
                            _text(data.get("reference product", data.get("product"))) or "",
                            _text(data.get("comment")) or "",
                            " ".join(categories),
                            " ".join(f"{system} {value}" for system, value in classifications),
                            " ".join(synonyms),
                        ),
                    )

                    for exchange in activity.exchanges():
                        exchange_batch.append(
                            _exchange_row(exchange.as_dict(), getattr(exchange, "id", None))
                        )
                        if len(exchange_batch) >= 1_000:
                            conn.executemany(
                                """INSERT INTO exchanges (
                                    brightway_id, output_database, output_code,
                                    input_database, input_code, type, amount, unit,
                                    name, reference_product, location, categories_text,
                                    uncertainty_type, loc, scale, shape, minimum,
                                    maximum, negative, formula, extra_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                exchange_batch,
                            )
                            exchange_count += len(exchange_batch)
                            db_exchanges += len(exchange_batch)
                            exchange_batch.clear()
                    activity_count += 1
                    db_activities += 1

                if exchange_batch:
                    conn.executemany(
                        """INSERT INTO exchanges (
                            brightway_id, output_database, output_code,
                            input_database, input_code, type, amount, unit,
                            name, reference_product, location, categories_text,
                            uncertainty_type, loc, scale, shape, minimum,
                            maximum, negative, formula, extra_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        exchange_batch,
                    )
                    exchange_count += len(exchange_batch)
                    db_exchanges += len(exchange_batch)
                    exchange_batch.clear()
                if progress:
                    print(
                        f"  {database_name}: {db_activities:,} activities, "
                        f"{db_exchanges:,} exchanges"
                    )

            fingerprint = _database_fingerprint(bd, database_names)
            metadata = {
                "schema_version": SCHEMA_VERSION,
                "built_at": dt.datetime.now(dt.UTC).isoformat(),
                "brightway_project": project_name,
                "bw2data_version": getattr(bd, "__version__", "unknown"),
                "source_databases": database_names,
                "source_fingerprint": fingerprint,
                "activity_count": activity_count,
                "exchange_count": exchange_count,
            }
            conn.executemany(
                "INSERT INTO projection_metadata(key, value) VALUES (?, ?)",
                [(key, _json_text(value)) for key, value in metadata.items()],
            )
            conn.commit()
            validation = _validate_projection(conn, activity_count, exchange_count)
            conn.execute("PRAGMA optimize")
            conn.close()
            conn = None
            os.replace(temp_path, destination)
        except Exception:
            if conn is not None:
                conn.close()
            temp_path.unlink(missing_ok=True)
            raise

    result = {
        "path": str(destination),
        "schema_version": SCHEMA_VERSION,
        "source_databases": database_names,
        **validation,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    if progress:
        print(
            f"Built {result['activity_count']:,} activities and "
            f"{result['exchange_count']:,} exchanges in "
            f"{result['elapsed_seconds']:.3f}s"
        )
        if result["unresolved_input_count"]:
            print(f"Warning: {result['unresolved_input_count']:,} input keys are unresolved")
    return result


def get_projection_status(
    *,
    path: str | pathlib.Path | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Return projection existence, metadata, and freshness."""
    bd = _set_project(project)
    projection_path = pathlib.Path(path) if path is not None else get_search_database_path()
    if not projection_path.exists():
        return {
            "exists": False,
            "fresh": False,
            "path": str(projection_path),
            "reason": "Search database has not been built",
        }
    try:
        uri = f"{projection_path.resolve().as_uri()}?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
            metadata = _metadata_values(conn)
    except (sqlite3.Error, OSError) as exc:
        return {
            "exists": True,
            "fresh": False,
            "path": str(projection_path),
            "reason": f"Search database could not be read: {exc}",
        }

    if metadata.get("schema_version") != SCHEMA_VERSION:
        return {
            "exists": True,
            "fresh": False,
            "path": str(projection_path),
            "reason": "Search database schema version is outdated",
            **metadata,
        }
    names = metadata.get("source_databases", [])
    missing = [name for name in names if name not in bd.databases]
    current = None if missing else _database_fingerprint(bd, names)
    fresh = (
        not missing
        and metadata.get("brightway_project") == bd.projects.current
        and metadata.get("source_fingerprint") == current
    )
    result = {
        "exists": True,
        "fresh": fresh,
        "path": str(projection_path),
        **metadata,
    }
    if not fresh:
        result["reason"] = (
            f"Source database(s) no longer exist: {missing}"
            if missing
            else "Brightway databases changed after this projection was built"
        )
    return result


def _require_fresh_projection(
    path: str | pathlib.Path | None = None,
    project: str | None = None,
) -> tuple[pathlib.Path, dict[str, Any]]:
    status = get_projection_status(path=path, project=project)
    if not status["fresh"]:
        raise RuntimeError(
            f"{status.get('reason', 'Search database is unavailable')}. "
            "Run `uv run python scripts/build_search_database.py`."
        )
    return pathlib.Path(status["path"]), status


def _read_only_connection(path: pathlib.Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }

    def authorize(action, arg1, arg2, _database, _trigger):
        # FTS5 internally reads PRAGMA data_version before consulting its
        # shadow tables. It is read-only and required for MATCH queries.
        if action == sqlite3.SQLITE_PRAGMA:
            return (
                sqlite3.SQLITE_OK
                if str(arg1).lower() == "data_version" and arg2 is None
                else sqlite3.SQLITE_DENY
            )
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    conn.set_authorizer(authorize)
    return conn


def query_search_database(
    sql: str,
    params: Sequence[Any] | Mapping[str, Any] | None = None,
    *,
    limit: int = 100,
    path: str | pathlib.Path | None = None,
    project: str | None = None,
    require_fresh: bool = True,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    """Execute one safe, read-only SQL query against the projection."""
    if not sql.strip():
        raise ValueError("SQL query cannot be empty")
    if limit < 1 or limit > 10_000:
        raise ValueError("limit must be between 1 and 10000")
    if require_fresh:
        projection_path, status = _require_fresh_projection(path, project)
    else:
        projection_path = pathlib.Path(path) if path is not None else get_search_database_path(project)
        status = {"fresh": None, "path": str(projection_path)}

    deadline = time.monotonic() + timeout_seconds
    conn = _read_only_connection(projection_path)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1_000)
    try:
        cursor = conn.execute(sql, params or ())
        rows = cursor.fetchmany(limit + 1)
        columns = [item[0] for item in cursor.description] if cursor.description else []
    except sqlite3.DatabaseError as exc:
        message = str(exc)
        if "not authorized" in message.lower() or "authorization denied" in message.lower():
            raise ValueError("Only read-only SELECT queries are allowed") from exc
        if "interrupted" in message.lower():
            raise TimeoutError(f"Query exceeded {timeout_seconds:g} seconds") from exc
        raise ValueError(f"Invalid search query: {message}") from exc
    finally:
        conn.close()
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "columns": columns,
        "rows": [list(row) for row in rows],
        "count": len(rows),
        "truncated": truncated,
        "fresh": status.get("fresh"),
        "built_at": status.get("built_at"),
        "source_databases": status.get("source_databases"),
    }


def _fts_expression(text: str) -> str:
    tokens = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", text, flags=re.UNICODE)
    if not tokens:
        raise ValueError("Search text must contain at least one letter or number")
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def search_activities(
    text: str,
    *,
    database: str | None = None,
    location: str | None = None,
    limit: int = 25,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Full-text search activities in the projection."""
    clauses = ["activities_fts MATCH ?"]
    params: list[Any] = [_fts_expression(text)]
    if database:
        clauses.append("a.database = ?")
        params.append(database)
    if location:
        clauses.append("a.location = ?")
        params.append(location)
    sql = f"""
        SELECT a.database, a.code, a.name, a.reference_product, a.location,
               a.unit, a.type, a.categories_text, bm25(activities_fts) AS rank
        FROM activities_fts AS f
        JOIN activities AS a
          ON a.database = f.database AND a.code = f.code
        WHERE {' AND '.join(clauses)}
        ORDER BY rank, a.name
    """
    result = query_search_database(sql, params, limit=limit, project=project)
    return [dict(zip(result["columns"], row)) for row in result["rows"]]


def get_activity_inputs(
    database: str,
    code: str,
    *,
    exchange_type: str | None = None,
    limit: int = 500,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Return readable direct inventory exchanges for one activity."""
    clauses = ["output_database = ?", "output_code = ?"]
    params: list[Any] = [database, code]
    if exchange_type:
        clauses.append("exchange_type = ?")
        params.append(exchange_type)
    sql = f"""
        SELECT input_database, input_code, input_name, input_product,
               input_location, exchange_type, amount, unit,
               uncertainty_type, loc, scale, minimum, maximum
        FROM exchange_details
        WHERE {' AND '.join(clauses)}
        ORDER BY ABS(amount) DESC, input_name
    """
    result = query_search_database(sql, params, limit=limit, project=project)
    return [dict(zip(result["columns"], row)) for row in result["rows"]]


def get_search_schema(project: str | None = None) -> dict[str, Any]:
    """Return the exact public SQLite schema and its query contract.

    The DDL comes from the live projection's ``sqlite_schema`` table. FTS5
    shadow tables and SQLite auto-indexes are intentionally omitted: they are
    storage internals, not supported query surfaces.
    """
    path, status = _require_fresh_projection(project=project)
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
        schema_objects = _public_schema_objects(conn)
    return {
        "schema_version": SCHEMA_VERSION,
        "schema_scope": "public searchable SQLite projection",
        "schema_objects": schema_objects,
        "freshness": {
            key: status.get(key)
            for key in ("fresh", "built_at", "source_databases", "activity_count", "exchange_count")
        },
        "query_contract": {
            "read_only": True,
            "allowed_statements": ["SELECT", "WITH ... SELECT"],
            "default_result_limit": 100,
            "result_limit_range": [1, 10_000],
            "timeout_seconds": 3,
            "denied": [
                "mutations",
                "multiple statements",
                "PRAGMA",
                "ATTACH",
                "extension loading",
            ],
        },
        "semantics": {
            "source_of_truth": "Brightway; this projection is disposable and read-only",
            "foreground_included": False,
            "exchange_direction": (
                "output_* identifies the consuming activity; input_* identifies "
                "the supplied activity or biosphere flow"
            ),
            "amount_meaning": (
                "Direct inventory quantity in the exchange unit; not an LCIA "
                "score or impact contribution"
            ),
            "recommended_exchange_view": "exchange_details",
        },
        "examples": {
            "activity_search": (
                "SELECT database, code, name, location, unit FROM activities "
                "WHERE database='bafu' AND name LIKE '%cotton%'"
            ),
            "full_text_search": (
                "SELECT database, code, name FROM activities_fts "
                "WHERE activities_fts MATCH '\"polylactide\"'"
            ),
            "direct_technosphere_inputs": (
                "SELECT input_database, input_code, input_name, input_location, "
                "amount, unit FROM exchange_details WHERE output_database='bafu' "
                "AND output_code='<code>' AND exchange_type='technosphere' "
                "ORDER BY ABS(amount) DESC"
            ),
            "direct_biosphere_exchanges": (
                "SELECT input_name, amount, unit FROM exchange_details "
                "WHERE output_database='bafu' AND output_code='<code>' "
                "AND exchange_type='biosphere' ORDER BY ABS(amount) DESC"
            ),
            "reverse_consumers": (
                "SELECT output_database, output_code, consumer_name, amount, unit "
                "FROM exchange_details WHERE input_database='bafu' "
                "AND input_code='<code>' AND exchange_type='technosphere'"
            ),
            "exchange_type_audit": (
                "SELECT exchange_type, COUNT(*) AS exchange_count FROM "
                "exchange_details WHERE output_database='bafu' "
                "AND output_code='<code>' GROUP BY exchange_type"
            ),
        },
    }


def _public_schema_objects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return exact DDL for supported public relations and their indexes."""
    public_relations = (*PUBLIC_TABLES, *PUBLIC_VIEWS)
    placeholders = ",".join("?" for _ in public_relations)
    rows = conn.execute(
        f"""
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE sql IS NOT NULL
          AND (
            name IN ({placeholders})
            OR (type = 'index' AND tbl_name IN ({placeholders}))
          )
        ORDER BY
          CASE type WHEN 'table' THEN 1 WHEN 'view' THEN 2 WHEN 'index' THEN 3 ELSE 4 END,
          name
        """,
        (*public_relations, *public_relations),
    ).fetchall()

    objects = []
    for object_type, name, table_name, sql in rows:
        if object_type == "table" and sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
            object_type = "virtual_table"
        item = {"type": object_type, "name": name, "sql": sql}
        if object_type == "index":
            item["table"] = table_name
        objects.append(item)
    return objects
