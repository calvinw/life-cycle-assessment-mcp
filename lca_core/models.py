"""Typed public result contracts shared by the Python, MCP, and REST layers."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class InventoryResult(TypedDict):
    amount: float
    unit: str
    type: str


class ImpactResult(TypedDict):
    score: float
    unit: str


class ProcessContribution(TypedDict):
    process_id: str
    process_name: str
    direct_score: float
    percentage: float | None
    scope: Literal["foreground", "background"]


class ProcessContributionCategory(TypedDict):
    id: str
    label: str
    unit: str
    total_score: float
    processes: list[ProcessContribution]
    residual_score: float


class ProcessContributions(TypedDict):
    categories: list[ProcessContributionCategory]


class SankeyNode(TypedDict):
    id: str
    label: str
    kind: Literal["process", "resource", "emission", "final_product"]
    process_name: NotRequired[str]
    flow_name: NotRequired[str]
    scope: NotRequired[Literal["foreground", "background"]]


class SankeyLink(TypedDict):
    id: str
    source: str
    target: str
    kind: Literal["technosphere", "extraction", "emission", "final_product"]
    flow_name: str
    amount: float
    unit: str


class SankeyResult(TypedDict):
    nodes: list[SankeyNode]
    links: list[SankeyLink]
    available_units: list[str]


class LcaCoreResult(TypedDict):
    name: str
    method: str
    functional_unit: str
    lci: dict[str, InventoryResult]
    lcia: dict[str, ImpactResult]
    scaling_vector: dict[str, float]
    result_schema_version: Literal[2]
    process_contributions: ProcessContributions
    sankey: SankeyResult


class LcaResult(LcaCoreResult):
    svg_scaled: str
    svg_structure: str
