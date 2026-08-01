"""Private Phase 0 benchmarks for independent background contribution graphs.

This module intentionally does not participate in the public Python, MCP, or
REST API. It drives the existing schema-3 engine with an in-memory benchmark
configuration so that later graph-bundle work has numerical and performance
references.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
import pathlib
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from unittest import mock

import yaml

from . import engine


DEFAULT_CUTOFF = 0.001
DEFAULT_BIOSPHERE_CUTOFF = 0.0001
DEFAULT_MAX_DEPTH = 12
DEFAULT_MAX_CALCULATIONS = 1000


@dataclass(frozen=True)
class BenchmarkSettings:
    cutoff: float = DEFAULT_CUTOFF
    biosphere_cutoff: float = DEFAULT_BIOSPHERE_CUTOFF
    max_depth: int = DEFAULT_MAX_DEPTH
    max_calculations: int = DEFAULT_MAX_CALCULATIONS
    include_flows: bool = True

    def as_engine_config(self, categories: list[str]) -> dict:
        return {
            "categories": categories,
            "cutoff": self.cutoff,
            "biosphere_cutoff": self.biosphere_cutoff,
            "max_depth": self.max_depth,
            "max_calculations": self.max_calculations,
            "include_flows": self.include_flows,
        }


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def serialization_sizes(value: object) -> dict[str, int]:
    """Return deterministic compact-JSON and gzip byte counts."""
    raw = _compact_json_bytes(value)
    return {
        "raw_bytes": len(raw),
        "gzip_bytes": len(gzip.compress(raw, compresslevel=9, mtime=0)),
    }


def _source_with_graph_config(
    source: str,
    config: dict | None,
) -> str:
    spec = copy.deepcopy(engine._load_spec(source))
    if config is None:
        spec["lcia"].pop("contribution_graph", None)
    else:
        spec["lcia"]["contribution_graph"] = config
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)


def _numeric_graph_reference(graph: dict) -> dict:
    """Keep a compact fingerprint of an independent category graph."""
    numeric_payload = {
        "label": graph["label"],
        "total_score": graph["total_score"],
        "coverage": graph["coverage"],
        "unexpanded_score": graph["unexpanded_score"],
        "calculation_count": graph["calculation_count"],
        "nodes": [
            [
                node["activity_id"],
                node["depth"],
                node["supply_amount"],
                node["direct_score"],
                node["cumulative_score"],
                node["unexpanded_score"],
                node["terminal"],
            ]
            for node in graph["nodes"]
        ],
        "edges": [
            [
                edge["producer_id"],
                edge["consumer_id"],
                edge["flow_name"],
                edge["amount"],
                edge["unit"],
            ]
            for edge in graph["edges"]
        ],
        "flows": [
            [
                flow["process_occurrence_id"],
                flow["flow_name"],
                flow["amount"],
                flow["score"],
            ]
            for flow in graph["flows"]
        ],
    }
    return {
        "total_score": graph["total_score"],
        "coverage": graph["coverage"],
        "unexpanded_score": graph["unexpanded_score"],
        "sum_node_direct_score": math.fsum(
            node["direct_score"] for node in graph["nodes"]
        ),
        "sum_flow_score": math.fsum(flow["score"] for flow in graph["flows"]),
        "sha256": hashlib.sha256(_compact_json_bytes(numeric_payload)).hexdigest(),
    }


def _occurrence_path_keys(graph: dict) -> set[str]:
    """Estimate cross-category union membership from the unrolled tree paths.

    This is benchmark-only identity. It deliberately excludes category labels
    and traversal IDs while retaining parent path, activity identity, exchange
    values, and an ordinal for otherwise-identical sibling exchanges.
    """
    nodes = {node["id"]: node for node in graph["nodes"]}
    roots = [node["id"] for node in graph["nodes"] if node["kind"] == "functional_unit"]
    if len(roots) != 1:
        raise ValueError(f"Expected one functional-unit root in {graph['label']!r}.")
    root_id = roots[0]

    edge_by_child: dict[str, dict] = {}
    sibling_groups: dict[tuple, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        child = edge["producer_id"]
        if child in edge_by_child:
            raise ValueError(
                f"Occurrence {child!r} has multiple parents in {graph['label']!r}."
            )
        edge_by_child[child] = edge
        node = nodes[child]
        group = (
            edge["consumer_id"],
            node["activity_id"],
            node["database"],
            node["code"],
            edge["flow_name"],
            edge["amount"],
            edge["unit"],
        )
        sibling_groups[group].append(edge)

    sibling_ordinal: dict[str, int] = {}
    for edges in sibling_groups.values():
        for ordinal, edge in enumerate(
            sorted(edges, key=lambda item: item["producer_id"])
        ):
            sibling_ordinal[edge["producer_id"]] = ordinal

    keys_by_id: dict[str, tuple] = {root_id: ("functional_unit",)}

    def resolve(node_id: str) -> tuple:
        if node_id in keys_by_id:
            return keys_by_id[node_id]
        edge = edge_by_child.get(node_id)
        if edge is None:
            raise ValueError(
                f"Occurrence {node_id!r} is disconnected in {graph['label']!r}."
            )
        node = nodes[node_id]
        key = resolve(edge["consumer_id"]) + (
            (
                node["activity_id"],
                node["database"],
                node["code"],
                edge["flow_name"],
                edge["amount"],
                edge["unit"],
                sibling_ordinal[node_id],
            ),
        )
        keys_by_id[node_id] = key
        return key

    for node_id in nodes:
        resolve(node_id)
    return {
        hashlib.sha256(_compact_json_bytes(path)).hexdigest()
        for path in keys_by_id.values()
    }


def _run_graph_enabled(
    source: str,
    category_labels: list[str],
    settings: BenchmarkSettings,
) -> tuple[dict, float, dict[str, float]]:
    configured_source = _source_with_graph_config(
        source,
        (
            settings.as_engine_config(category_labels)
            if category_labels
            else None
        ),
    )
    original = engine.build_contribution_graph
    traversal_seconds: dict[str, float] = {}

    def timed_build_contribution_graph(**kwargs):
        started = time.perf_counter()
        graph = original(**kwargs)
        traversal_seconds[graph["label"]] = time.perf_counter() - started
        return graph

    started = time.perf_counter()
    with mock.patch.object(
        engine,
        "build_contribution_graph",
        side_effect=timed_build_contribution_graph,
    ):
        result = engine.run_analysis(configured_source)
    total_seconds = time.perf_counter() - started
    return result, total_seconds, traversal_seconds


def benchmark_example(
    path: pathlib.Path,
    *,
    settings: BenchmarkSettings = BenchmarkSettings(),
    repeat: int = 1,
) -> dict:
    """Benchmark one YAML example with the current independent graph schema."""
    if repeat <= 0:
        raise ValueError("repeat must be a positive integer.")
    source = path.read_text()
    baseline_source = _source_with_graph_config(source, None)

    lcia_samples: list[float] = []
    total_samples: list[float] = []
    traversal_samples: dict[str, list[float]] = defaultdict(list)
    reference_digest: str | None = None
    final_result: dict | None = None

    for _ in range(repeat):
        started = time.perf_counter()
        baseline = engine.run_analysis(baseline_source)
        lcia_samples.append(time.perf_counter() - started)
        category_labels = [
            label
            for label, impact in baseline["lcia"].items()
            if not math.isclose(
                impact["score"],
                0.0,
                abs_tol=engine.NUMERIC_ABS_TOLERANCE,
            )
        ]
        result, total_seconds, traversals = _run_graph_enabled(
            source,
            category_labels,
            settings,
        )
        total_samples.append(total_seconds)
        for label, elapsed in traversals.items():
            traversal_samples[label].append(elapsed)

        digest = hashlib.sha256(
            _compact_json_bytes(result["contribution_graphs"])
        ).hexdigest()
        if reference_digest is not None and digest != reference_digest:
            raise RuntimeError(
                f"Independent graph output changed between repeats for {path}."
            )
        reference_digest = digest
        final_result = result

    assert final_result is not None
    graphs = final_result["contribution_graphs"]
    union_keys: set[str] = set()
    category_rows = []
    for graph in graphs:
        union_keys.update(_occurrence_path_keys(graph))
        category_rows.append(
            {
                "label": graph["label"],
                "unit": graph["unit"],
                "traversal_seconds": statistics.median(
                    traversal_samples[graph["label"]]
                ),
                "traversal_second_samples": traversal_samples[graph["label"]],
                "calculation_count": graph["calculation_count"],
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "flow_count": len(graph["flows"]),
                "graph_sizes": serialization_sizes(graph),
                "numeric_reference": _numeric_graph_reference(graph),
            }
        )

    try:
        report_path = path.resolve().relative_to(engine.ROOT).as_posix()
    except ValueError:
        report_path = str(path.resolve())

    return {
        "example": path.name,
        "path": report_path,
        "method": final_result["method"],
        "repeat": repeat,
        "nonzero_category_count": len(graphs),
        "lcia_only_seconds": statistics.median(lcia_samples),
        "lcia_only_second_samples": lcia_samples,
        "all_nonzero_total_seconds": statistics.median(total_samples),
        "all_nonzero_total_second_samples": total_samples,
        "total_node_count": sum(len(graph["nodes"]) for graph in graphs),
        "total_edge_count": sum(len(graph["edges"]) for graph in graphs),
        "total_flow_count": sum(len(graph["flows"]) for graph in graphs),
        "union_node_count": len(union_keys),
        "union_node_count_method": "category_independent_occurrence_path_v1",
        "response_sizes": serialization_sizes(final_result),
        "independent_graphs_sha256": reference_digest,
        "categories": category_rows,
    }


def synthetic_serialization_fixture(
    *,
    node_count: int = 1000,
    flow_count: int = 1500,
) -> dict:
    """Build a deterministic large graph fixture without running Brightway."""
    if node_count <= 0 or flow_count < 0:
        raise ValueError("node_count must be positive and flow_count non-negative.")
    nodes = []
    for index in range(node_count):
        nodes.append(
            {
                "id": f"occurrence:synthetic:{index:04d}",
                "kind": "functional_unit" if index == 0 else "process",
                "activity_id": None if index == 0 else f"activity:{index % 317:04d}",
                "process_name": (
                    "Synthetic functional unit"
                    if index == 0
                    else f"Synthetic process {index % 317:04d}"
                ),
                "database": None if index == 0 else "synthetic_background",
                "code": None if index == 0 else f"process-{index % 317:04d}",
                "location": None if index == 0 else "SYN",
                "scope": None if index == 0 else "background",
                "depth": min(index, 12),
                "supply_amount": 1.0 / (index + 1),
                "unit": "kilogram",
                "direct_score": index * 1e-7,
                "cumulative_score": (node_count - index) * 1e-7,
                "cumulative_percentage": (node_count - index) / node_count * 100,
                "unexpanded_score": index % 11 * 1e-9,
                "terminal": index >= node_count - 100,
            }
        )
    edges = [
        {
            "id": f"edge:synthetic:{index:04d}",
            "source": f"occurrence:synthetic:{index:04d}",
            "target": f"occurrence:synthetic:{(index - 1) // 2:04d}",
            "consumer_id": f"occurrence:synthetic:{(index - 1) // 2:04d}",
            "producer_id": f"occurrence:synthetic:{index:04d}",
            "flow_name": f"Synthetic product {index % 317:04d}",
            "amount": 1.0 / (index + 1),
            "unit": "kilogram",
        }
        for index in range(1, node_count)
    ]
    flows = [
        {
            "id": f"flow:synthetic:{index:04d}",
            "process_occurrence_id": (
                f"occurrence:synthetic:{index % node_count:04d}"
            ),
            "flow_name": f"Synthetic emission {index % 151:04d}",
            "categories": ["air", "unspecified"],
            "kind": "emission",
            "amount": 1.0 / (index + 1),
            "unit": "kilogram",
            "score": index * 1e-8,
            "percentage": index / max(flow_count, 1) * 100,
        }
        for index in range(flow_count)
    ]
    return {
        "result_schema_version": 3,
        "contribution_graphs": [
            {
                "id": "contribution-graph:synthetic",
                "label": "synthetic impact",
                "unit": "synthetic unit",
                "total_score": 1.0,
                "cutoff": DEFAULT_CUTOFF,
                "biosphere_cutoff": DEFAULT_BIOSPHERE_CUTOFF,
                "max_depth": DEFAULT_MAX_DEPTH,
                "max_calculations": node_count,
                "calculation_count": node_count,
                "coverage": 0.9,
                "unexpanded_score": 0.1,
                "status": "partial",
                "nodes": nodes,
                "edges": edges,
                "flows": flows,
                "activity_contributions": [],
            }
        ],
    }
