from __future__ import annotations

import polars as pl

from cardre.nodes.build.clustering import VariableClusteringNode


def _dataset() -> pl.DataFrame:
    return pl.DataFrame({
        "age": [25, 30, 35, 40, 45, 50],
        "income": [50000, 60000, 70000, 80000, 90000, 100000],
        "credit_risk_class": ["good", "bad", "good", "bad", "good", "bad"],
    })


class TestVariableClusteringNode:
    def test_woe_train_missing_evidence_uses_singleton_pass_through(self, node_harness):
        out = node_harness(
            VariableClusteringNode,
            frames={"train": _dataset()},
            params={
                "method": "correlation_threshold",
                "input_representation": "woe_train",
                "threshold": 0.7,
                "candidate_limit": 50,
            },
        )
        report = next(a for a in out.staged if a.role == "report")
        warnings = report.payload.get("warnings", [])
        assert any("WOE_EVIDENCE_MISSING" in str(w) for w in warnings)

    def test_raw_train_succeeds_with_correlation_threshold(self, node_harness):
        out = node_harness(
            VariableClusteringNode,
            frames={"train": _dataset()},
            params={
                "method": "correlation_threshold",
                "input_representation": "raw_train",
                "threshold": 0.7,
                "candidate_limit": 50,
            },
        )
        assert out.staged

    def test_insufficient_candidates_uses_singleton_pass_through(self, node_harness):
        out = node_harness(
            VariableClusteringNode,
            frames={"train": pl.DataFrame({"age": [25, 30]})},
            params={
                "method": "correlation_threshold",
                "input_representation": "raw_train",
                "threshold": 0.7,
                "candidate_limit": 50,
            },
        )
        report = next(a for a in out.staged if a.role == "report")
        warnings = report.payload.get("warnings", [])
        assert any("INSUFFICIENT_CANDIDATES" in str(w) for w in warnings)
