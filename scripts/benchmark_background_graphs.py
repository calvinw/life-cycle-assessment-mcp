#!/usr/bin/env python3
"""Run Phase 0 background-graph benchmarks without changing the public API."""

from __future__ import annotations

import argparse
import datetime
import importlib.metadata
import json
import pathlib
import platform
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lca_core import engine
from lca_core.benchmark import (
    BenchmarkSettings,
    benchmark_example,
    serialization_sizes,
    synthetic_serialization_fixture,
)


DEFAULT_EXAMPLES = sorted(
    list((ROOT / "mock_examples").glob("*.yaml"))
    + list((ROOT / "bafu_examples").glob("*.yaml"))
)


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1000 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1000
    raise AssertionError("unreachable")


def _display_path(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _markdown(report: dict) -> str:
    lines = [
        "# Phase 0 Background Graph Benchmark",
        "",
        f"Measured: {report['measured_at']}",
        "",
        "Re-run with:",
        "",
        "```sh",
        "uv run python scripts/benchmark_background_graphs.py",
        "```",
        "",
        (
            "LCIA-only time is one complete current engine run with contribution "
            "graphs disabled (foreground setup, factorized LCI, every LCIA category, "
            "and core-result assembly). Per-category traversal time covers the "
            "existing Brightway traversal plus schema-3 graph adaptation. "
            "All-nonzero time is one complete engine run with independent traversal "
            "for every numerically nonzero category. Times are medians of the "
            "recorded samples."
        ),
        "",
        (
            "Response sizes cover the core result without REST SVG strings and use "
            "compact UTF-8 JSON plus deterministic gzip level 9. Counts sum the "
            "current independent schema-3 category graphs; union nodes use the "
            "benchmark-only category-independent occurrence-path fingerprint."
        ),
        "",
        "| Example | LCIA only | All nonzero | Categories | Nodes | Edges | Flows | Union nodes | Raw | Gzip |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["examples"]:
        lines.append(
            "| {example} | {lcia:.3f} s | {total:.3f} s | {categories} | "
            "{nodes:,} | {edges:,} | {flows:,} | {union:,} | {raw} | {gzip} |".format(
                example=row["example"],
                lcia=row["lcia_only_seconds"],
                total=row["all_nonzero_total_seconds"],
                categories=row["nonzero_category_count"],
                nodes=row["total_node_count"],
                edges=row["total_edge_count"],
                flows=row["total_flow_count"],
                union=row["union_node_count"],
                raw=_human_bytes(row["response_sizes"]["raw_bytes"]),
                gzip=_human_bytes(row["response_sizes"]["gzip_bytes"]),
            )
        )

    for row in report["examples"]:
        lines.extend(
            [
                "",
                f"## {row['example']}",
                "",
                "| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for category in row["categories"]:
            lines.append(
                "| {label} | {seconds:.3f} s | {calculations:,} | {nodes:,} | "
                "{edges:,} | {flows:,} | {raw} | {gzip} |".format(
                    label=category["label"].replace("|", "\\|"),
                    seconds=category["traversal_seconds"],
                    calculations=category["calculation_count"],
                    nodes=category["node_count"],
                    edges=category["edge_count"],
                    flows=category["flow_count"],
                    raw=_human_bytes(category["graph_sizes"]["raw_bytes"]),
                    gzip=_human_bytes(category["graph_sizes"]["gzip_bytes"]),
                )
            )

    fixture = report["synthetic_serialization_fixture"]
    lines.extend(
        [
            "",
            "## Synthetic serialization fixture",
            "",
            (
                f"{fixture['node_count']:,} nodes, {fixture['edge_count']:,} edges, "
                f"and {fixture['flow_count']:,} flows serialize to "
                f"{_human_bytes(fixture['sizes']['raw_bytes'])} raw and "
                f"{_human_bytes(fixture['sizes']['gzip_bytes'])} gzipped."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark independent all-nonzero background graphs."
    )
    parser.add_argument(
        "examples",
        nargs="*",
        type=pathlib.Path,
        help="YAML examples; defaults to every mock_examples and bafu_examples YAML.",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--cutoff", type=float, default=0.001)
    parser.add_argument("--biosphere-cutoff", type=float, default=0.0001)
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--max-calculations", type=int, default=1000)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=ROOT / "benchmarks/background_graph_phase0.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=pathlib.Path,
        default=ROOT / "benchmarks/background_graph_phase0.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeat <= 0:
        raise SystemExit("--repeat must be positive")
    examples = [path.resolve() for path in (args.examples or DEFAULT_EXAMPLES)]
    settings = BenchmarkSettings(
        cutoff=args.cutoff,
        biosphere_cutoff=args.biosphere_cutoff,
        max_depth=args.max_depth,
        max_calculations=args.max_calculations,
        include_flows=True,
    )

    # Database setup and projection checks are startup concerns, not benchmark
    # work, so complete them before starting any timers.
    engine._ensure_project()

    rows = []
    for index, path in enumerate(examples, start=1):
        print(f"[{index}/{len(examples)}] {path.relative_to(ROOT)}", flush=True)
        row = benchmark_example(path, settings=settings, repeat=args.repeat)
        rows.append(row)
        print(
            f"  LCIA {row['lcia_only_seconds']:.3f}s; "
            f"all nonzero {row['all_nonzero_total_seconds']:.3f}s; "
            f"{row['nonzero_category_count']} categories; "
            f"{row['total_node_count']} nodes; {row['total_edge_count']} edges; "
            f"{row['total_flow_count']} flows; {row['union_node_count']} union nodes",
            flush=True,
        )

    fixture = synthetic_serialization_fixture()
    fixture_graph = fixture["contribution_graphs"][0]
    report = {
        "benchmark_schema_version": 1,
        "measured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "settings": {
            "cutoff": settings.cutoff,
            "biosphere_cutoff": settings.biosphere_cutoff,
            "max_depth": settings.max_depth,
            "max_calculations": settings.max_calculations,
            "include_flows": settings.include_flows,
        },
        "measurement_definitions": {
            "lcia_only_seconds": (
                "Complete current engine run with contribution graphs disabled: "
                "foreground setup, factorized LCI, every LCIA category, and core "
                "result assembly."
            ),
            "category_traversal_seconds": (
                "Existing Brightway traversal plus schema-3 graph adaptation for "
                "one category."
            ),
            "all_nonzero_total_seconds": (
                "Complete current engine run with an independent graph traversal "
                "for every category whose total is not within 1e-12 of zero."
            ),
            "response_sizes": (
                "Compact UTF-8 JSON core result without REST SVG strings; gzip is "
                "level 9 with mtime zero."
            ),
            "union_node_count": (
                "Benchmark-only union of category-independent occurrence paths; "
                "not a public or production node identity."
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "brightway_project": engine.BRIGHTWAY_PROJECT,
            "brightway25": _version("brightway25"),
            "bw2calc": _version("bw2calc"),
            "bw2data": _version("bw2data"),
            "bw-graph-tools": _version("bw-graph-tools"),
        },
        "examples": rows,
        "synthetic_serialization_fixture": {
            "node_count": len(fixture_graph["nodes"]),
            "edge_count": len(fixture_graph["edges"]),
            "flow_count": len(fixture_graph["flows"]),
            "sizes": serialization_sizes(fixture),
            "sha256": __import__("hashlib").sha256(
                json.dumps(
                    fixture,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    args.markdown_output.write_text(_markdown(report))
    print(f"Wrote {_display_path(args.output)}", flush=True)
    print(f"Wrote {_display_path(args.markdown_output)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
