"""Adapt Brightway graph traversal results to the public LCA result contract."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict

import bw2data as bd
from bw_graph_tools import (
    GraphTraversalSettings,
    NewNodeEachVisitGraphTraversal,
)

from .models import ContributionGraph


def _stable_id(kind: str, *parts: object) -> str:
    canonical = "\x1f".join(str(part) for part in parts)
    slug_source = str(parts[0]) if parts else kind
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-")[:48]
    slug = slug or "item"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{slug}:{digest}"


def _percentage(score: float, total: float) -> float | None:
    if math.isclose(total, 0, abs_tol=1e-12):
        return None
    return score / total * 100


def _clean_noise(value: float, total: float) -> float:
    tolerance = max(abs(total), 1.0) * 1e-12
    return 0.0 if abs(value) <= tolerance else value


def _node_by_matrix_index(lca, mapping_name: str, index: int):
    mapping = getattr(lca.dicts, mapping_name)
    return bd.get_node(id=mapping.reversed[index])


def _flow_kind(flow) -> str:
    categories = " ".join(str(item).lower() for item in flow.get("categories", []))
    return "extraction" if "natural resource" in categories else "emission"


def build_contribution_graph(
    *,
    lca,
    spec: dict,
    label: str,
    unit: str,
    config: dict,
    foreground_metadata: dict[int, dict],
) -> ContributionGraph:
    """Traverse an already-characterized LCA object without creating a new LCA."""
    total = float(lca.score)
    graph_id = _stable_id("contribution-graph", label)
    root_id = _stable_id(
        "contribution-occurrence",
        spec.get("name", ""),
        label,
        "functional-unit",
    )

    if math.isclose(total, 0, abs_tol=1e-12):
        fu = spec["functional_unit"]
        return {
            "id": graph_id,
            "label": label,
            "unit": unit,
            "total_score": total,
            "cutoff": config["cutoff"],
            "biosphere_cutoff": config["biosphere_cutoff"],
            "max_depth": config["max_depth"],
            "max_calculations": config["max_calculations"],
            "calculation_count": 0,
            "coverage": None,
            "unexpanded_score": 0.0,
            "status": "zero_total",
            "nodes": [
                {
                    "id": root_id,
                    "kind": "functional_unit",
                    "activity_id": None,
                    "process_name": fu["description"],
                    "database": None,
                    "code": None,
                    "location": None,
                    "scope": None,
                    "depth": 0,
                    "supply_amount": float(fu["amount"]),
                    "unit": fu["unit"],
                    "direct_score": 0.0,
                    "cumulative_score": total,
                    "cumulative_percentage": None,
                    "unexpanded_score": 0.0,
                    "terminal": False,
                }
            ],
            "edges": [],
            "flows": [],
            "activity_contributions": [],
        }

    traversal = NewNodeEachVisitGraphTraversal(
        lca,
        GraphTraversalSettings(
            cutoff=config["cutoff"],
            biosphere_cutoff=config["biosphere_cutoff"],
            max_calc=config["max_calculations"],
            max_depth=config["max_depth"],
            skip_coproducts=False,
            separate_biosphere_flows=config["include_flows"],
        ),
    )
    traversal.traverse()

    raw_nodes = traversal.nodes
    raw_edges = traversal.edges
    raw_flows = traversal.flows
    occurrence_ids: dict[int, str] = {-1: root_id}
    node_metadata: dict[int, dict] = {}

    for unique_id, raw in raw_nodes.items():
        if unique_id == -1:
            continue
        activity = _node_by_matrix_index(lca, "activity", raw.activity_index)
        foreground = foreground_metadata.get(activity.id)
        if foreground:
            activity_id = foreground["activity_id"]
            process_name = foreground["process_name"]
            scope = "foreground"
        else:
            activity_id = _stable_id(
                "background-process",
                activity.get("database", ""),
                activity.get("code", ""),
            )
            process_name = activity.get("name", str(activity.key))
            scope = "background"
        occurrence_id = _stable_id(
            "contribution-occurrence",
            label,
            unique_id,
            activity_id,
        )
        occurrence_ids[unique_id] = occurrence_id
        node_metadata[unique_id] = {
            "activity": activity,
            "activity_id": activity_id,
            "process_name": process_name,
            "scope": scope,
            "database": (
                foreground["database"]
                if foreground
                else activity.get("database", "")
            ),
            "code": (
                foreground["code"]
                if foreground
                else activity.get("code", "")
            ),
            "location": (
                foreground["location"]
                if foreground
                else activity.get("location")
            ),
        }

    children: dict[int, list[int]] = defaultdict(list)
    for edge in raw_edges:
        children[edge.consumer_unique_id].append(edge.producer_unique_id)

    fu = spec["functional_unit"]
    public_nodes: list[dict] = []
    for unique_id, raw in sorted(
        raw_nodes.items(), key=lambda item: (item[1].depth, item[0])
    ):
        child_cumulative = sum(
            float(raw_nodes[child_id].cumulative_score)
            for child_id in children.get(unique_id, [])
        )
        direct = 0.0 if unique_id == -1 else float(raw.direct_emissions_score)
        cumulative = float(raw.cumulative_score)
        unexpanded = _clean_noise(
            cumulative - direct - child_cumulative,
            total,
        )
        if unique_id == -1:
            public_nodes.append(
                {
                    "id": root_id,
                    "kind": "functional_unit",
                    "activity_id": None,
                    "process_name": fu["description"],
                    "database": None,
                    "code": None,
                    "location": None,
                    "scope": None,
                    "depth": 0,
                    "supply_amount": float(fu["amount"]),
                    "unit": fu["unit"],
                    "direct_score": 0.0,
                    "cumulative_score": cumulative,
                    "cumulative_percentage": _percentage(cumulative, total),
                    "unexpanded_score": unexpanded,
                    "terminal": False,
                }
            )
            continue

        metadata = node_metadata[unique_id]
        activity = metadata["activity"]
        public_nodes.append(
            {
                "id": occurrence_ids[unique_id],
                "kind": "process",
                "activity_id": metadata["activity_id"],
                "process_name": metadata["process_name"],
                "database": metadata["database"],
                "code": metadata["code"],
                "location": metadata["location"],
                "scope": metadata["scope"],
                "depth": int(raw.depth),
                "supply_amount": float(raw.supply_amount),
                "unit": activity.get("unit", ""),
                "direct_score": direct,
                "cumulative_score": cumulative,
                "cumulative_percentage": _percentage(cumulative, total),
                "unexpanded_score": unexpanded,
                "terminal": bool(raw.terminal),
            }
        )

    public_edges: list[dict] = []
    for edge_index, edge in enumerate(raw_edges):
        producer_id = occurrence_ids[edge.producer_unique_id]
        consumer_id = occurrence_ids[edge.consumer_unique_id]
        product = _node_by_matrix_index(lca, "product", edge.product_index)
        flow_name = (
            product.get("reference product")
            or product.get("name")
            or str(product.key)
        )
        public_edges.append(
            {
                "id": _stable_id(
                    "contribution-edge",
                    label,
                    edge_index,
                    producer_id,
                    consumer_id,
                ),
                # Retain producer-to-consumer direction for Sankey compatibility,
                # while explicit endpoint names make tree traversal unambiguous.
                "source": producer_id,
                "target": consumer_id,
                "consumer_id": consumer_id,
                "producer_id": producer_id,
                "flow_name": flow_name,
                "amount": float(edge.amount),
                "unit": product.get("unit", ""),
            }
        )

    public_flows: list[dict] = []
    if config["include_flows"]:
        for flow_index, raw in enumerate(raw_flows):
            flow = _node_by_matrix_index(lca, "biosphere", raw.flow_index)
            process_occurrence_id = occurrence_ids[raw.activity_unique_id]
            score = float(raw.score)
            public_flows.append(
                {
                    "id": _stable_id(
                        "contribution-flow",
                        label,
                        flow_index,
                        process_occurrence_id,
                        flow.get("code", ""),
                    ),
                    "process_occurrence_id": process_occurrence_id,
                    "flow_name": flow.get("name", str(flow.key)),
                    "categories": list(flow.get("categories", [])),
                    "kind": _flow_kind(flow),
                    "amount": float(raw.amount),
                    "unit": flow.get("unit", ""),
                    "score": score,
                    "percentage": _percentage(score, total),
                }
            )

    activity_rows: dict[str, dict] = {}
    visited_direct = 0.0
    for unique_id, metadata in node_metadata.items():
        raw = raw_nodes[unique_id]
        direct = float(raw.direct_emissions_score)
        visited_direct += direct
        activity_id = metadata["activity_id"]
        if activity_id not in activity_rows:
            activity = metadata["activity"]
            activity_rows[activity_id] = {
                "activity_id": activity_id,
                "process_name": metadata["process_name"],
                "database": metadata["database"],
                "code": metadata["code"],
                "location": metadata["location"],
                "scope": metadata["scope"],
                "direct_score": 0.0,
                "percentage": None,
                "occurrence_count": 0,
            }
        activity_rows[activity_id]["direct_score"] += direct
        activity_rows[activity_id]["occurrence_count"] += 1

    for row in activity_rows.values():
        row["direct_score"] = _clean_noise(row["direct_score"], total)
        row["percentage"] = _percentage(row["direct_score"], total)

    unexpanded = _clean_noise(total - visited_direct, total)
    coverage = visited_direct / total
    status = "complete" if unexpanded == 0 else "partial"

    return {
        "id": graph_id,
        "label": label,
        "unit": unit,
        "total_score": total,
        "cutoff": config["cutoff"],
        "biosphere_cutoff": config["biosphere_cutoff"],
        "max_depth": config["max_depth"],
        "max_calculations": config["max_calculations"],
        "calculation_count": int(traversal.calculation_count),
        "coverage": coverage,
        "unexpanded_score": unexpanded,
        "status": status,
        "nodes": public_nodes,
        "edges": public_edges,
        "flows": public_flows,
        "activity_contributions": sorted(
            activity_rows.values(),
            key=lambda row: (
                -abs(row["direct_score"]),
                row["process_name"],
                row["activity_id"],
            ),
        ),
    }
