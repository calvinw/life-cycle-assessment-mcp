"""Calculate activities that already exist in a Brightway project."""

from __future__ import annotations

from typing import Any

import bw2calc as bc
import bw2data as bd


def _resolve_method(method_name: str, impact_category: str) -> tuple[str, ...]:
    matches = [
        method
        for method in bd.methods
        if method
        and method[0] == method_name
        and " | ".join(method[1:]) == impact_category
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Multiple methods match '{method_name} | {impact_category}': {matches}"
        )

    available = [
        " | ".join(method[1:])
        for method in bd.methods
        if method and method[0] == method_name
    ]
    raise ValueError(
        f"LCIA method '{method_name} | {impact_category}' is not installed. "
        f"Available categories: {available}"
    )


def calculate_activity(
    database: str,
    method_name: str,
    impact_category: str,
    *,
    project: str,
    amount: float = 1.0,
    product_name: str | None = None,
    code: str | None = None,
    location: str | None = None,
    activity_type: str | None = "product",
) -> dict[str, Any]:
    """Calculate one imported activity using an exact LCIA method path.

    Select the activity by its Brightway ``code`` or by ``product_name``.
    Product nodes are selected by default because Brightway 2.5 requires the
    functional-unit demand to target a product rather than a process node.
    """
    if not code and not product_name:
        raise ValueError("Either code or product_name is required")

    bd.projects.set_current(project)
    if database not in bd.databases:
        raise ValueError(
            f"Database '{database}' is not installed in Brightway project '{project}'"
        )

    matches = []
    for activity in bd.Database(database):
        if code and activity.get("code") != code:
            continue
        if not code and activity.get("name") != product_name:
            continue
        if location is not None and activity.get("location") != location:
            continue
        if activity_type is not None and activity.get("type") != activity_type:
            continue
        matches.append(activity)

    selector = f"code '{code}'" if code else f"name '{product_name}'"
    if not matches:
        raise ValueError(
            f"No {activity_type or 'activity'} with {selector} found in '{database}'"
        )
    if len(matches) > 1:
        choices = [
            {
                "code": activity.get("code"),
                "name": activity.get("name"),
                "location": activity.get("location"),
                "type": activity.get("type"),
            }
            for activity in matches
        ]
        raise ValueError(f"Activity selector is ambiguous: {choices}")

    activity = matches[0]
    method = _resolve_method(method_name, impact_category)
    lca = bc.LCA({activity: amount}, method)
    lca.lci()
    lca.lcia()

    return {
        "project": project,
        "database": database,
        "activity": {
            "code": activity.get("code"),
            "name": activity.get("name"),
            "location": activity.get("location"),
            "type": activity.get("type"),
        },
        "amount": float(amount),
        "method": list(method),
        "score": float(lca.score),
        "unit": bd.methods[method].get("unit", ""),
    }
