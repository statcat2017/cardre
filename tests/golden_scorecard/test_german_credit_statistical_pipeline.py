"""Sections F–H: Statistical equivalence tests for Cardre's full pipeline.

These run Cardre's own import / split / binning / selection steps and
compare distributional properties to the R reference rather than
expecting exact match.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import ExecutionContext, StepSpec, json_logical_hash
from cardre.nodes import (
    CalculateWoeIvNode,
    FineClassingNode,
    SplitTrainTestOotNode,
    VariableClusteringNode,
    VariableSelectionNode,
)
from cardre.nodes.prep import DefineModellingMetadataNode, ImportGermanCreditNode
from tests.golden_scorecard.helpers import r_col, CARDRE_TO_R


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def imported_data(golden_raw_data):
    """Import once per module and cache the artifacts."""
    from tests.helpers import make_store
    store, tmp = make_store()

    spec = StepSpec(
        step_id="import", node_type="cardre.import_fixture_uci_german_credit",
        node_version="1", category="transform",
        params={"source_path": str(golden_raw_data)},
        params_hash=json_logical_hash({"source_path": str(golden_raw_data)}),
        parent_step_ids=[], branch_label="", position=0,
    )
    ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=spec, parent_run_steps=[],
        input_artifacts=[], validated_params={"source_path": str(golden_raw_data)},
        runtime_metadata={},
    )
    imp_art = ImportGermanCreditNode().run(ctx).artifacts[0]

    meta_params = {
        "target_column": "credit_risk_class",
        "good_values": ["1"], "bad_values": ["2"], "indeterminate_values": [],
    }
    meta_spec = StepSpec(
        step_id="meta", node_type="cardre.define_modelling_metadata",
        node_version="1", category="transform",
        params=meta_params, params_hash=json_logical_hash(meta_params),
        parent_step_ids=["import"], branch_label="", position=0,
    )
    meta_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=meta_spec, parent_run_steps=[],
        input_artifacts=[imp_art], validated_params=meta_params, runtime_metadata={},
    )
    meta_art = DefineModellingMetadataNode().run(meta_ctx).artifacts[0]
    return {"store": store, "tmp": tmp, "import_art": imp_art, "meta_art": meta_art}


@pytest.fixture(scope="module")
def split_data(imported_data):
    """2-way stratified split via SplitTrainTestOotNode."""
    store = imported_data["store"]
    split_params = {
        "strategy": "random_stratified",
        "train_fraction": 0.6, "test_fraction": 0.4, "oot_fraction": 0.0,
        "target_column": "credit_risk_class", "random_seed": 30,
    }
    split_spec = StepSpec(
        step_id="split", node_type="cardre.split_train_test_oot",
        node_version="2", category="transform",
        params=split_params, params_hash=json_logical_hash(split_params),
        parent_step_ids=["import", "meta"], branch_label="", position=0,
    )
    split_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=split_spec, parent_run_steps=[],
        input_artifacts=[imported_data["import_art"], imported_data["meta_art"]],
        validated_params=split_params, runtime_metadata={},
    )
    out = SplitTrainTestOotNode().run(split_ctx)
    train_art = next(a for a in out.artifacts if a.role == "train")
    test_art = next(a for a in out.artifacts if a.role == "test")
    return {
        "store": store,
        "meta_art": imported_data["meta_art"],
        "train": pl.read_parquet(store.artifact_path(train_art)),
        "test": pl.read_parquet(store.artifact_path(test_art)),
        "train_art": train_art,
        "test_art": test_art,
    }


@pytest.fixture(scope="module")
def binned_data(split_data):
    """FineClassing + CalculateWoeIvNode."""
    store = split_data["store"]
    meta_art = split_data["meta_art"]

    fine_params = {
        "method": "fine_classing",
        "max_bins": 20, "min_bin_fraction": 0.05,
        "missing_policy": "separate_bin", "max_categorical_levels": 50,
        "exclude_columns": [],
    }
    fine_spec = StepSpec(
        step_id="fine", node_type="cardre.binning",
        node_version="1", category="fit",
        params=fine_params, params_hash=json_logical_hash(fine_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    fine_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=fine_spec, parent_run_steps=[],
        input_artifacts=[split_data["train_art"], meta_art],
        validated_params=fine_params, runtime_metadata={},
    )
    bin_art = FineClassingNode().run(fine_ctx).artifacts[0]

    woe_params = {"zero_cell_policy": "block", "smoothing": None, "purpose": "initial"}
    woe_spec = StepSpec(
        step_id="woe-iv", node_type="cardre.calculate_woe_iv",
        node_version="1", category="selection",
        params=woe_params, params_hash=json_logical_hash(woe_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    woe_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=woe_spec, parent_run_steps=[],
        input_artifacts=[split_data["train_art"], bin_art, meta_art],
        validated_params=woe_params, runtime_metadata={},
    )
    woe_out = CalculateWoeIvNode().run(woe_ctx)

    iv_evidence = None
    iv_art = None
    for art in woe_out.artifacts:
        if art.artifact_type == "report":
            path = store.artifact_path(art)
            if path.suffix == ".parquet":
                df = pl.read_parquet(path)
                if "iv" in df.columns:
                    iv_evidence, iv_art = df, art
            elif path.suffix == ".json":
                import json as _json
                data = _json.loads(path.read_text())
                if "variables" in data and iv_evidence is None:
                    iv_evidence = data

    return {
        "store": store, "meta_art": meta_art,
        "train_art": split_data["train_art"],
        "bin_art": bin_art, "iv_art": iv_art, "iv_evidence": iv_evidence,
    }


@pytest.fixture(scope="module")
def selected_data(binned_data):
    """VariableClustering + VariableSelection."""
    store = binned_data["store"]
    iv_art = binned_data.get("iv_art")
    if iv_art is None:
        pytest.fail("No IV ranking artifact — missing evidence is a FAILURE")

    cluster_params = {"correlation_threshold": 0.7, "candidate_limit": 50}
    cluster_spec = StepSpec(
        step_id="cluster", node_type="cardre.variable_clustering",
        node_version="1", category="selection",
        params=cluster_params, params_hash=json_logical_hash(cluster_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    cluster_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=cluster_spec, parent_run_steps=[],
        input_artifacts=[binned_data["train_art"]],
        validated_params=cluster_params, runtime_metadata={},
    )
    cluster_art = VariableClusteringNode().run(cluster_ctx).artifacts[0]

    sel_params = {"min_iv": 0.02, "max_variables": 15,
                   "manual_includes": [], "manual_excludes": []}
    sel_spec = StepSpec(
        step_id="select", node_type="cardre.variable_selection",
        node_version="1", category="selection",
        params=sel_params, params_hash=json_logical_hash(sel_params),
        parent_step_ids=[], branch_label="", position=0,
    )
    sel_ctx = ExecutionContext(
        store=store, run_id="r1", plan_version_id="pv1",
        step_spec=sel_spec, parent_run_steps=[],
        input_artifacts=[iv_art, cluster_art],
        validated_params=sel_params, runtime_metadata={},
    )
    sel_def = json.loads(store.artifact_path(
        VariableSelectionNode().run(sel_ctx).artifacts[0]
    ).read_text())
    return {"selected_vars": {s["variable"] for s in sel_def.get("selected", [])}}


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestStatisticalSplit:
    def test_split_bad_rate(self, split_data):
        pop_bad_rate = 300 / 1000
        for role in ("train", "test"):
            sub = split_data[role]
            bad_count = sub.filter(pl.col("credit_risk_class") == "2").height
            rate = bad_count / sub.height
            assert abs(rate - pop_bad_rate) < 0.03

    def test_split_row_counts(self, split_data):
        assert split_data["train"].height + split_data["test"].height == 1000
        assert split_data["train"].height >= 500
        assert split_data["test"].height >= 300


class TestStatisticalBinning:
    def test_iv_ranking_correlation(self, binned_data, golden_csv):
        evidence = binned_data["iv_evidence"]
        if evidence is None:
            pytest.fail("No IV evidence artifact — missing evidence is a FAILURE")

        if isinstance(evidence, pl.DataFrame):
            cardre_ivs = {row["variable"]: float(row["iv"])
                          for row in evidence.iter_rows(named=True)}
        elif isinstance(evidence, dict):
            cardre_ivs = {v["variable_name"]: float(v["iv"])
                          for v in evidence.get("variables", [])}
        else:
            pytest.fail(f"Unknown IV evidence type: {type(evidence)}")

        r_bins = golden_csv["bins_adj"]
        r_ivs = {}
        for row in r_bins.iter_rows(named=True):
            var = row["variable"]
            r_ivs[var] = max(r_ivs.get(var, 0), float(row["total_iv"]))

        common = set(cardre_ivs.keys()) & set(r_ivs.keys())
        if len(common) < 3:
            pytest.fail(f"Too few overlapping variables ({len(common)})")

        cr = sorted(common, key=lambda v: cardre_ivs[v], reverse=True)
        rr = sorted(common, key=lambda v: r_ivs[v], reverse=True)
        co = {v: i for i, v in enumerate(cr)}
        ro = {v: i for i, v in enumerate(rr)}
        n = len(common)
        d_sq = sum((co[v] - ro[v]) ** 2 for v in common)
        spearman = 1 - (6 * d_sq) / (n * (n * n - 1))
        assert spearman > 0.4, f"Spearman = {spearman:.3f}"


class TestStatisticalSelection:
    def test_selection_overlap_with_r(self, selected_data, golden_csv):
        r_selected = {r_col(v.replace("_woe", ""))
                      for v in golden_csv["selected_terms"]["term"].to_list()}
        cardre_selected = selected_data["selected_vars"]
        intersection = r_selected & cardre_selected
        union = r_selected | cardre_selected
        jaccard = len(intersection) / max(len(union), 1)
        assert jaccard > 0.45, (
            f"Jaccard = {jaccard:.2f} ({len(intersection)}/{len(union)})"
        )
