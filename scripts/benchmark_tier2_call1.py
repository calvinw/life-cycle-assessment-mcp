"""Measure the Call 1 cost Tier 2 adds by publishing provider intensities.

Method mirrors benchmarks/tier1_after_optimization.md: one process, one
discarded warm-up call, then seven recorded calls, phase instrumentation plus an
outer perf_counter, all values reported in milliseconds.

Usage:
    LCA_BACKGROUND_INTENSITY_CACHE=off|on python scripts/benchmark_tier2_call1.py [--cold]

``--cold`` clears the intensity cache before every recorded sample, so each call
pays for a fresh background solve per category instead of a warm lookup.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lca_core import LCAEngine  # noqa: E402
from lca_core import background_intensity  # noqa: E402
from lca_core import engine as core_engine  # noqa: E402

WORKLOAD = "bafu_examples/plastic_broom.yaml"
SAMPLES = 7


def phase_seconds(phases: dict, name: str) -> float:
    value = phases.get(name)
    if isinstance(value, dict):
        return float(value.get("total_seconds", 0.0))
    return float(value or 0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold", action="store_true")
    parser.add_argument(
        "--cold-category",
        action="store_true",
        help="Keep the built entry and its factorization; drop only the per-method "
             "vectors, which is the realistic first-use-of-a-category miss.",
    )
    args = parser.parse_args()

    engine = LCAEngine()
    engine.ensure_ready()
    source = (ROOT / WORKLOAD).read_text()

    captured: list[dict] = []
    original = core_engine._emit_performance_log

    def capture(operation, started, phases):
        captured.append(dict(phases))
        return original(operation, started, phases)

    core_engine._emit_performance_log = capture

    engine.run_base(source)  # discarded warm-up
    captured.clear()

    rows = []
    for _ in range(SAMPLES):
        if args.cold:
            background_intensity.clear_cache()
        elif args.cold_category:
            for entry in background_intensity._entries.values():
                entry.y_by_method.clear()
        started = time.perf_counter()
        result = engine.run_base(source)
        wall = (time.perf_counter() - started) * 1000.0
        phases = captured[-1]
        rows.append(
            {
                "wall": wall,
                "link_intensities": phase_seconds(
                    phases, "background_link_intensities_per_category"
                ) * 1000.0,
                "foreground": phase_seconds(phases, "temporary_foreground_creation") * 1000.0,
                "lci": phase_seconds(phases, "lci_factorization") * 1000.0,
                "lcia": phase_seconds(phases, "lcia_calculation_and_direct_contributions") * 1000.0,
                "links": len(result.get("background_link_intensities") or []),
                "field": "background_link_intensities" in result,
            }
        )

    core_engine._emit_performance_log = original

    def summary(key: str) -> dict:
        values = [row[key] for row in rows]
        return {
            "median": round(statistics.median(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }

    print(json.dumps({
        "mode": background_intensity.configured_mode(),
        "cold": args.cold,
        "cold_category": args.cold_category,
        "workload": WORKLOAD,
        "samples": SAMPLES,
        "field_present": rows[0]["field"],
        "links": rows[0]["links"],
        "wall_ms": summary("wall"),
        "link_intensities_ms": summary("link_intensities"),
        "foreground_ms": summary("foreground"),
        "lci_ms": summary("lci"),
        "lcia_ms": summary("lcia"),
        "raw_wall_ms": [round(row["wall"], 3) for row in rows],
        "raw_link_ms": [round(row["link_intensities"], 3) for row in rows],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
