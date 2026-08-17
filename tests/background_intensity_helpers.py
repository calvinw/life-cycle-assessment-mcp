from contextlib import contextmanager
from functools import lru_cache
import pathlib

import numpy as np
from scipy.sparse.linalg import splu

from lca_core import engine as core_engine


ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKGROUND_LINKED_PATHS = (
    "bafu_examples/cotton_fiber_bafu.yaml",
    "bafu_examples/plastic_broom.yaml",
    "bafu_examples/polyester_tshirt_bafu.yaml",
    "bafu_examples/wool_yarn_bafu.yaml",
    "mock_examples/mock_plastic_broom.yaml",
    "mock_examples/mock_plastic_broom_simple.yaml",
    "mock_examples/mock_storage_bin.yaml",
)
ALL_SPEC_PATHS = (
    "case_studies/cotton_fiber.yaml",
    "case_studies/jacket.yaml",
    "case_studies/polyester_tshirt.yaml",
    "case_studies/wool_yarn.yaml",
    "mock_examples/mock_plastic_broom.yaml",
    "mock_examples/mock_plastic_broom_simple.yaml",
    "mock_examples/mock_storage_bin.yaml",
    "bafu_examples/cotton_fiber_bafu.yaml",
    "bafu_examples/plastic_broom.yaml",
    "bafu_examples/polyester_tshirt_bafu.yaml",
    "bafu_examples/wool_yarn_bafu.yaml",
)


def load_spec(relative_path: str) -> tuple[str, dict]:
    source = (ROOT / relative_path).read_text()
    return source, core_engine._load_spec(source)


def configured_methods(spec: dict) -> list[tuple]:
    method_name = spec["lcia"]["method_name"]
    available = sorted(
        [method for method in core_engine.bd.methods if method[0] == method_name],
        key=lambda method: method[-1],
    )
    resolved = core_engine._resolve_contribution_graph_methods(
        available,
        core_engine._impact_category_config(spec),
    )
    return [method for method in available if method in resolved]


def resolve_method(method_name: str, category: str) -> tuple:
    available = sorted(
        [method for method in core_engine.bd.methods if method[0] == method_name],
        key=lambda method: method[-1],
    )
    resolved = core_engine._resolve_contribution_graph_methods(
        available,
        {"categories": [category]},
    )
    return next(method for method in available if method in resolved)


@contextmanager
def foreground_lca(source: str, method: tuple):
    core_engine._ensure_project()
    spec = core_engine._load_spec(source)
    with core_engine._request_foreground(spec) as (activities, _, _):
        reference = activities[spec["reference_process"]]
        amount = float(spec["functional_unit"]["amount"])
        lca = core_engine.bc.LCA(demand={reference: amount}, method=method)
        lca.lci()
        yield spec, activities, lca


def matrix_partition(lca, activities: dict) -> dict:
    foreground_activity_ids = {activity.id for activity in activities.values()}
    foreground_databases = {
        activity.get("database") for activity in activities.values()
    }

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

    foreground_product_rows = []
    background_product_rows = []
    background_product_ids = {}
    for node_id, index in lca.dicts.product.items():
        node = core_engine.bd.get_node(id=node_id)
        if node.get("database") in foreground_databases:
            foreground_product_rows.append(index)
        else:
            background_product_rows.append(index)
            background_product_ids[index] = node_id

    foreground_product_rows = np.array(sorted(foreground_product_rows), dtype=int)
    background_product_rows = np.array(sorted(background_product_rows), dtype=int)
    return {
        "foreground_activity_columns": foreground_activity_columns,
        "background_activity_columns": background_activity_columns,
        "foreground_product_rows": foreground_product_rows,
        "background_product_rows": background_product_rows,
        "background_product_ids": [
            background_product_ids[index] for index in background_product_rows
        ],
    }


def direct_intensities(lca) -> np.ndarray:
    characterized_biosphere = (
        lca.characterization_matrix @ lca.biosphere_matrix
    )
    return np.asarray(characterized_biosphere.sum(axis=0)).ravel()


def solve_adjoint(lca) -> tuple[np.ndarray, np.ndarray]:
    direct = direct_intensities(lca)
    transpose_lu = splu(lca.technosphere_matrix.T.tocsc())
    cumulative = np.asarray(transpose_lu.solve(direct)).ravel()
    return direct, cumulative


def background_y_from_full_lca(lca, activities: dict) -> dict[int, float]:
    partition = matrix_partition(lca, activities)
    _, cumulative = solve_adjoint(lca)
    return {
        node_id: float(cumulative[index])
        for index, node_id in zip(
            partition["background_product_rows"],
            partition["background_product_ids"],
            strict=True,
        )
    }


def background_database_names(spec: dict) -> tuple[str, ...]:
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


@lru_cache(maxsize=None)
def precomputed_background_y(
    database_names: tuple[str, ...], method: tuple
) -> dict[int, float]:
    if not database_names:
        return {}
    core_engine._ensure_project()
    demand = {
        next(iter(core_engine.bd.Database(database_name))): 1.0
        for database_name in database_names
    }
    lca = core_engine.bc.LCA(demand=demand, method=method)
    lca.lci()
    lca.lcia()
    _, cumulative = solve_adjoint(lca)
    return {
        node_id: float(cumulative[index])
        for node_id, index in lca.dicts.product.items()
    }
