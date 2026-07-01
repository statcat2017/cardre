from __future__ import annotations

from cardre.audit import RunStepRecord
from cardre._evidence.models import RoleMetrics
from cardre.evidence import EvidenceKind, ValidationMetrics
import cardre.services.comparison_service as comparison_service


def test_build_comparison_content_uses_typed_validation_metrics(monkeypatch):
    class FakeStore:
        def get_branch_step_map(self, branch_id, plan_version_id):
            return [
                {
                    "canonical_step_id": "validation-metrics",
                    "step_id": "validation-metrics",
                }
            ]

        def get_latest_successful_run_step_for_step(self, plan_version_id, step_id, branch_id=None):
            artifact_id = "baseline-validation" if branch_id is None else "challenger-validation"
            return RunStepRecord(
                run_step_id=f"rs-{plan_version_id}-{branch_id or 'baseline'}",
                run_id=f"run-{plan_version_id}",
                step_id=step_id,
                plan_version_id=plan_version_id,
                status="succeeded",
                started_at="2026-01-01T00:00:00+00:00",
                finished_at="2026-01-01T00:00:01+00:00",
                input_artifact_ids=[],
                output_artifact_ids=[artifact_id],
                execution_fingerprint={},
                warnings=[],
                errors=[],
            )

    class FakeReader:
        def __init__(self, store):
            self.store = store

        def read_optional(self, artifact_id, kind):
            if kind not in (EvidenceKind.VALIDATION_METRICS, EvidenceKind.VALIDATION_EVIDENCE):
                return None
            metrics = {
                "baseline-validation": ValidationMetrics(
                    metrics_by_role={
                        "train": RoleMetrics(row_count=100, auc=0.81, gini=0.62, ks=0.41),
                        "test": RoleMetrics(row_count=40, auc=0.79, gini=0.58, ks=0.37),
                        "oot": RoleMetrics(row_count=30, auc=0.77, gini=0.54, ks=0.33),
                    },
                    psi={"score": 0.1},
                    target={},
                    gates=[],
                    warnings=[],
                    source_artifact_id=artifact_id,
                ),
                "challenger-validation": ValidationMetrics(
                    metrics_by_role={
                        "train": RoleMetrics(row_count=100, auc=0.83, gini=0.66, ks=0.44),
                        "test": RoleMetrics(row_count=40, auc=0.80, gini=0.60, ks=0.38),
                        "oot": RoleMetrics(row_count=30, auc=0.78, gini=0.56, ks=0.35),
                    },
                    psi={"score": 0.2},
                    target={},
                    gates=[],
                    warnings=[],
                    source_artifact_id=artifact_id,
                ),
            }
            return metrics[artifact_id]

    monkeypatch.setattr(comparison_service, "ArtifactEvidenceReader", FakeReader)

    content = comparison_service._build_comparison_content(  # noqa: SLF001
        FakeStore(),
        plan_version_id_baseline="pv-baseline",
        plan_version_id_challenger="pv-challenger",
        branch_id_baseline="baseline",
        branch_id_challenger="challenger",
        spec={
            "include_woe_iv": False,
            "include_model": False,
            "include_validation": True,
            "include_cutoff": False,
        },
    )

    assert content["validation"]["roles"]["train"]["baseline"]["auc"] == 0.81
    assert content["validation"]["roles"]["train"]["challenger"]["auc"] == 0.83
    assert content["validation"]["roles"]["test"]["baseline"]["ks"] == 0.37
    assert content["validation"]["roles"]["oot"]["challenger"]["gini"] == 0.56
