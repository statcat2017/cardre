"""Tests for cardre._evidence.summaries — per-kind summariser dispatch."""

from __future__ import annotations

from cardre._evidence.summaries import summarise


def _fake_row(artifact_type: str = "", evidence_kind: str = "",
              role: str = "", schema_version: str = "") -> dict:
    """Build a minimal fake artifact row dict."""
    row: dict = {
        "artifact_id": "art-1",
        "artifact_type": artifact_type,
        "role": role,
        "media_type": "application/json",
        "logical_hash": "abc",
    }
    meta: dict = {}
    if schema_version:
        meta["schema_version"] = schema_version
    if evidence_kind:
        meta["evidence_kind"] = evidence_kind
    if meta:
        row["metadata"] = meta
    return row


class _FakePayload:
    """Minimal fake payload with optional attributes."""

    def __init__(self, **kwargs) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_summary_profile():
    row = _fake_row(artifact_type="profile", role="train")
    payload = _FakePayload(
        row_count=10000,
        column_count=42,
        dataset_role="train",
    )
    summary, warnings = summarise(row, payload)
    assert summary["row_count"] == 10000
    assert summary["column_count"] == 42
    assert summary["dataset_role"] == "train"
    assert warnings == []


def test_summary_woe_iv():
    class FakeVariable:
        status = "included"
        variable_name = "income_band"
        iv = 0.42

    payload = _FakePayload(variables=[FakeVariable()])
    row = _fake_row(schema_version="cardre.woe_iv_evidence.v1")
    summary, _ = summarise(row, payload)
    assert summary["selected_variable_count"] == 1
    assert summary["iv_min"] == 0.42
    assert summary["iv_max"] == 0.42
    assert len(summary["top_variables"]) == 1
    assert summary["top_variables"][0]["name"] == "income_band"


def test_summary_target_definition():
    payload = _FakePayload(
        target_column="default",
        good_values=[0],
        bad_values=[1],
        extra={"event_rate": 0.05},
    )
    row = _fake_row(schema_version="cardre.modelling_metadata.v1")
    summary, _ = summarise(row, payload)
    assert summary["target_column"] == "default"
    assert summary["event_rate"] == 0.05


def test_summary_split():
    payload = _FakePayload(
        strategy="random",
        row_counts={"train": 8000, "test": 2000, "oot": 0},
    )
    row = _fake_row(schema_version="cardre.split_summary.v1")
    summary, _ = summarise(row, payload)
    assert summary["train_count"] == 8000
    assert summary["test_count"] == 2000
    assert summary["oot_count"] == 0


def test_summary_binning():
    class FakeBin:
        bin_id = "b1"

    class FakeVariable:
        variable_name = "age"
        bins = [FakeBin(), FakeBin()]

    payload = _FakePayload(variables=[FakeVariable()])
    row = _fake_row(schema_version="cardre.bin_definition.v1")
    summary, _ = summarise(row, payload)
    assert summary["variable_count"] == 1
    assert summary["bin_total"] == 2
    assert "missing_handling" in summary


def test_summary_logistic_model():
    payload = _FakePayload(
        features=[{"name": "x1"}, {"name": "x2"}],
        coefficients=[0.5, -0.3],
        training={"status": "converged"},
    )
    row = _fake_row(schema_version="cardre.model_artifact.v1")
    summary, _ = summarise(row, payload)
    assert summary["variable_count"] == 2
    assert summary["coefficient_count"] == 2
    assert summary["fit_status"] == "converged"


def test_summary_score_scaling():
    payload = _FakePayload(
        min_score=200, max_score=800, pdo=20,
        base_odds="50:1", base_score=600,
    )
    row = _fake_row(schema_version="cardre.score_scaling.v1")
    summary, _ = summarise(row, payload)
    assert summary["score_min"] == 200
    assert summary["score_max"] == 800
    assert summary["pdo"] == 20


def test_summary_validation_metrics():
    class FakeRole:
        gini = 0.45
        ks = 0.31
        auc = 0.78

    payload = _FakePayload(
        metrics_by_role={"train": FakeRole()},
        psi={"train": 0.01},
    )
    row = _fake_row(schema_version="cardre.validation_metrics.v1")
    summary, _ = summarise(row, payload)
    assert summary["gini"] == 0.45
    assert summary["ks"] == 0.31
    assert summary["auc"] == 0.78


def test_summary_report_bundle():
    payload = _FakePayload(summary={"ready": True, "blockers": [], "warnings": ["No OOT"]})
    row = _fake_row(schema_version="cardre.report_bundle.v1")
    summary, _ = summarise(row, payload)
    assert summary["ready"] is True
    assert summary["blocker_count"] == 0
    assert summary["warning_count"] == 1


def test_unsupported_kind_returns_generic():
    row = _fake_row(artifact_type="exotic-thing")
    row["metadata"] = {"evidence_kind": "exotic-thing"}
    summary, _ = summarise(row, _FakePayload())
    assert summary.get("unsupported_kind") is True



