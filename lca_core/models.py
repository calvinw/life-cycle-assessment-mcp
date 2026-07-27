"""Typed public result contracts shared by the Python, MCP, and REST layers."""

from __future__ import annotations

from typing import Literal

from typing_extensions import NotRequired, TypedDict


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


class ContributionGraphNode(TypedDict):
    id: str
    kind: Literal["functional_unit", "process"]
    activity_id: str | None
    process_name: str
    database: str | None
    code: str | None
    location: str | None
    scope: Literal["foreground", "background"] | None
    depth: int
    supply_amount: float
    unit: str
    direct_score: float
    cumulative_score: float
    cumulative_percentage: float | None
    unexpanded_score: float
    terminal: bool


class ContributionGraphEdge(TypedDict):
    id: str
    source: str
    target: str
    consumer_id: str
    producer_id: str
    flow_name: str
    amount: float
    unit: str


class ContributionGraphFlow(TypedDict):
    id: str
    process_occurrence_id: str
    flow_name: str
    categories: list[str]
    kind: Literal["extraction", "emission"]
    amount: float
    unit: str
    score: float
    percentage: float | None


class ContributionGraphActivity(TypedDict):
    activity_id: str
    process_name: str
    database: str
    code: str
    location: str | None
    scope: Literal["foreground", "background"]
    direct_score: float
    percentage: float | None
    occurrence_count: int


class ContributionGraph(TypedDict):
    id: str
    label: str
    unit: str
    total_score: float
    cutoff: float
    biosphere_cutoff: float
    max_depth: int | None
    max_calculations: int
    calculation_count: int
    coverage: float | None
    unexpanded_score: float
    status: Literal["complete", "partial", "zero_total"]
    nodes: list[ContributionGraphNode]
    edges: list[ContributionGraphEdge]
    flows: list[ContributionGraphFlow]
    activity_contributions: list[ContributionGraphActivity]


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
    result_schema_version: Literal[3]
    process_contributions: ProcessContributions
    contribution_graphs: list[ContributionGraph]
    sankey: SankeyResult


class LcaResult(LcaCoreResult):
    svg_scaled: str
    svg_structure: str
