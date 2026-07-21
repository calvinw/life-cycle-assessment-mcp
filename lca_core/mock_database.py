"""Install the bundled, generated mock background database."""

from __future__ import annotations

import hashlib
import pathlib
from typing import Any

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_PATH = ROOT / "mock_background" / "database.yaml"
DATABASE_NAME = "mock_background"
SOURCE_HASH_FIELD = "mock_source_sha256"


def _load_source(source_path: pathlib.Path) -> tuple[dict[str, Any], str]:
    raw = source_path.read_bytes()
    source = yaml.safe_load(raw)
    if not isinstance(source, dict) or not isinstance(source.get("database"), dict):
        raise ValueError(f"Mock database source is invalid: {source_path}")
    if source["database"].get("name") != DATABASE_NAME:
        raise ValueError(
            f"Mock database source must declare database.name as '{DATABASE_NAME}'."
        )
    activities = source.get("activities")
    if not isinstance(activities, list) or not activities:
        raise ValueError("Mock database source must contain at least one activity.")
    return source, hashlib.sha256(raw).hexdigest()


def _find_biosphere_flow(bd, database: str, name: str, compartment: str):
    matches = [
        flow
        for flow in bd.Database(database)
        if flow.get("name") == name
        and tuple(flow.get("categories", ()))[:1] == (compartment,)
    ]
    if not matches:
        raise ValueError(
            f"Mock biosphere flow '{name}' in compartment '{compartment}' "
            f"was not found in '{database}'."
        )
    # The category with no sub-compartment is the normal unspecified flow and
    # has broad LCIA method coverage. Stable code order makes fallback explicit.
    return sorted(matches, key=lambda flow: (len(flow.get("categories", ())), flow["code"]))[0]


def _validate_activities(activities: list[dict[str, Any]]) -> set[str]:
    codes = [activity.get("code") for activity in activities]
    if any(not isinstance(code, str) or not code for code in codes):
        raise ValueError("Every mock activity must have a non-empty code.")
    if len(codes) != len(set(codes)):
        raise ValueError("Mock activity codes must be unique.")
    known_codes = set(codes)
    for activity in activities:
        for exchange in activity.get("technosphere", []):
            if exchange.get("activity") not in known_codes:
                raise ValueError(
                    f"Mock activity '{activity['code']}' references unknown activity "
                    f"'{exchange.get('activity')}'."
                )
    return known_codes


def ensure_mock_background_database(
    bd,
    *,
    biosphere_database: str = "biosphere3",
    source_path: str | pathlib.Path = DEFAULT_SOURCE_PATH,
) -> dict[str, Any]:
    """Install or refresh the bundled mock database in the active project.

    The database is generated entirely from a version-controlled YAML source.
    Replacing an outdated copy is therefore safe and deterministic; it never
    contains request or user-authored state.
    """
    path = pathlib.Path(source_path)
    source, source_hash = _load_source(path)
    activities = source["activities"]
    _validate_activities(activities)

    if biosphere_database not in bd.databases:
        raise RuntimeError(
            f"'{biosphere_database}' must be installed before '{DATABASE_NAME}'."
        )

    if DATABASE_NAME in bd.databases:
        metadata = bd.databases[DATABASE_NAME]
        if (
            metadata.get(SOURCE_HASH_FIELD) == source_hash
            and metadata.get("number") == len(activities)
        ):
            return {
                "database": DATABASE_NAME,
                "activities": len(activities),
                "changed": False,
                "source_sha256": source_hash,
            }
        del bd.databases[DATABASE_NAME]

    data: dict[tuple[str, str], dict[str, Any]] = {}
    biosphere_cache: dict[tuple[str, str], Any] = {}
    for activity in activities:
        code = activity["code"]
        key = (DATABASE_NAME, code)
        exchanges = [
            {
                "input": key,
                "amount": float(activity.get("production_amount", 1.0)),
                "type": "production",
            }
        ]
        for exchange in activity.get("technosphere", []):
            exchanges.append(
                {
                    "input": (DATABASE_NAME, exchange["activity"]),
                    "amount": float(exchange["amount"]),
                    "type": "technosphere",
                }
            )
        for exchange in activity.get("biosphere", []):
            identity = (exchange["flow"], exchange.get("compartment", "air"))
            flow = biosphere_cache.get(identity)
            if flow is None:
                flow = _find_biosphere_flow(
                    bd, biosphere_database, identity[0], identity[1]
                )
                biosphere_cache[identity] = flow
            exchanges.append(
                {
                    "input": flow.key,
                    "amount": float(exchange["amount"]),
                    "type": "biosphere",
                }
            )
        data[key] = {
            "name": activity["name"],
            "reference product": activity["reference_product"],
            "location": activity.get("location", "MOCK"),
            "unit": activity["unit"],
            "type": "process",
            "comment": source["database"].get("description", ""),
            "exchanges": exchanges,
        }

    database = bd.Database(DATABASE_NAME)
    database.write(data)
    bd.databases[DATABASE_NAME].update(
        {
            SOURCE_HASH_FIELD: source_hash,
            "mock_schema_version": source["database"].get("version"),
            "title": source["database"].get("title"),
        }
    )
    bd.databases.flush()
    return {
        "database": DATABASE_NAME,
        "activities": len(activities),
        "changed": True,
        "source_sha256": source_hash,
    }
