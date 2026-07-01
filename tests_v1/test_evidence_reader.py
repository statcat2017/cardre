from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.models import (
    ApplyModelEvidence,
    ApplyWoeEvidence,
    ComparisonArtifact,
    ExclusionSummary,
    ExplainabilityReport,
    FairnessReport,
    FeatureSelectionEvidence,
    HyperparameterTuningEvidence,
    ProfileSummary,
    ProxyRiskReport,
    ReportBundleEvidence,
    ResamplingEvidence,
    RunManifestEvidence,
    ModelArtifact,
    SplitSummary,
    TechnicalManifestIndex,
    WoeTransformEvidence,
)
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre.audit import ArtifactRef, json_logical_hash, physical_hash, relative_path


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "evidence"


def _register_json_artifact(
    store,
    fixture_name: str,
    *,
    stem: str,
    role: str,
    artifact_type: str | None = None,
    schema_version: str | None = None,
) -> ArtifactRef:
    payload = json.loads((FIXTURE_DIR / fixture_name).read_text())
    path = store.root / "artifacts" / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True))
    art = ArtifactRef(
        artifact_id=f"{stem}_1",
        artifact_type=artifact_type or role,
        role=role,
        path=relative_path(path, store.root),
        physical_hash=physical_hash(path),
        logical_hash=json_logical_hash(payload),
        media_type="application/json",
        metadata={"schema_version": schema_version or payload.get("schema_version", "")},
    )
    store.register_artifact(art)
    return art


def _register_inline_json_artifact(
    store,
    payload: dict,
    *,
    stem: str,
    role: str,
    artifact_type: str | None = None,
    schema_version: str | None = None,
) -> ArtifactRef:
    path = store.root / "artifacts" / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True))
    art = ArtifactRef(
        artifact_id=f"{stem}_1",
        artifact_type=artifact_type or role,
        role=role,
        path=relative_path(path, store.root),
        physical_hash=physical_hash(path),
        logical_hash=json_logical_hash(payload),
        media_type="application/json",
        metadata={"schema_version": schema_version or payload.get("schema_version", "")},
    )
    store.register_artifact(art)
    return art


def _run_step(artifact_ids: list[str]) -> object:
    return namedtuple("RunStepRecord", "step_id output_artifact_ids")("step_1", artifact_ids)


def test_reader_returns_typed_launch_critical_models(store, monkeypatch) -> None:
    reader = ArtifactEvidenceReader(store)

    split_art = _register_json_artifact(store, "split_summary.json", stem="split", role="report")
    profile_art = _register_json_artifact(store, "profile_summary.json", stem="profile", role="report")
    exclusion_art = _register_json_artifact(store, "exclusion_summary.json", stem="exclusion", role="report")
    woe_transform_art = _register_json_artifact(store, "woe_transform_evidence.json", stem="woe-transform", role="report")
    apply_woe_art = _register_json_artifact(store, "apply_woe_evidence.json", stem="apply-woe", role="report")
    apply_model_art = _register_json_artifact(store, "apply_model_evidence.json", stem="apply-model", role="report")
    report_bundle_art = _register_json_artifact(store, "report_bundle.json", stem="report-bundle", role="report")
    run_manifest_art = _register_json_artifact(store, "run_manifest.json", stem="run-manifest", role="audit", artifact_type="run_manifest")
    comparison_art = _register_json_artifact(store, "comparison_artifact.json", stem="comparison", role="comparison", artifact_type="branch_comparison")
    technical_index_art = _register_inline_json_artifact(
        store,
        {
            "schema_version": "cardre.technical_manifest_index.v1",
            "manifests": [
                {
                    "artifact_id": "manifest_1",
                    "kind": "run_manifest",
                }
            ],
        },
        stem="technical-index",
        role="report",
        artifact_type="report",
    )

    split = reader.find([split_art], EvidenceKind.SPLIT_SUMMARY)
    profile = reader.find([profile_art], EvidenceKind.PROFILE_SUMMARY)
    exclusion = reader.find([exclusion_art], EvidenceKind.EXCLUSION_SUMMARY)
    woe_transform = reader.find([woe_transform_art], EvidenceKind.WOE_TRANSFORM_EVIDENCE)
    apply_woe = reader.find([apply_woe_art], EvidenceKind.APPLY_WOE_EVIDENCE)
    apply_model = reader.find([apply_model_art], EvidenceKind.APPLY_MODEL_EVIDENCE)
    report_bundle = reader.read_report_bundle(report_bundle_art.artifact_id)
    run_manifest = reader.read_run_manifest(run_manifest_art.artifact_id)
    comparison = reader.find([comparison_art], EvidenceKind.COMPARISON_ARTIFACT)
    technical_index = reader.find([technical_index_art], EvidenceKind.TECHNICAL_MANIFEST_INDEX)

    assert isinstance(split, SplitSummary)
    assert split.row_counts["train"] == 70
    assert isinstance(profile, ProfileSummary)
    assert profile.row_count == 100
    assert profile.column_count == 4
    assert profile.columns == ["age", "income", "target", "segment"]
    assert isinstance(exclusion, ExclusionSummary)
    assert exclusion.rows_excluded == 8
    assert isinstance(woe_transform, WoeTransformEvidence)
    assert woe_transform.transformed_variables == ["age_woe", "income_woe"]
    assert isinstance(apply_woe, ApplyWoeEvidence)
    assert apply_woe.woe_table_artifact_id == "woe_1"
    assert isinstance(apply_model, ApplyModelEvidence)
    assert apply_model.model_artifact_id == "model_1"
    assert isinstance(report_bundle, ReportBundleEvidence)
    assert report_bundle.project_id == "project_1"
    assert isinstance(run_manifest, RunManifestEvidence)
    assert run_manifest.steps[0]["step_id"] == "step_1"
    assert isinstance(comparison, ComparisonArtifact)
    assert comparison.challenger_branch_id == "challenger_1"
    assert isinstance(technical_index, TechnicalManifestIndex)
    assert technical_index.manifests[0]["kind"] == "run_manifest"

    run_step = _run_step([report_bundle_art.artifact_id, apply_model_art.artifact_id])
    assert reader.read_required_step_output(run_step, EvidenceKind.REPORT_BUNDLE).project_id == "project_1"
    assert reader.read_optional_step_output(run_step, EvidenceKind.REPORT_BUNDLE).project_id == "project_1"
    assert len(reader.read_all_step_outputs(run_step, EvidenceKind.REPORT_BUNDLE)) == 1

    summary = reader.summarise_artifact(report_bundle_art.artifact_id, EvidenceKind.REPORT_BUNDLE)
    assert summary.kind == "report_bundle"
    assert summary.source_artifact_id == report_bundle_art.artifact_id

    legacy_profile_art = _register_inline_json_artifact(
        store,
        {
            "row_count": 42,
            "column_count": 3,
            "columns": ["age", "income", "target"],
            "dtypes": {"age": "Int64", "income": "Float64", "target": "Int64"},
            "null_counts": {"age": 0, "income": 0, "target": 0},
            "numeric_stats": {},
            "profile_steps": [],
        },
        stem="legacy-profile",
        role="report",
        artifact_type="report",
        schema_version="",
    )
    legacy_profile_summary = reader.summarise_artifact(legacy_profile_art.artifact_id)
    assert legacy_profile_summary.kind == "profile_summary"

    step_summaries = reader.summarise_step_outputs(run_step, EvidenceKind.REPORT_BUNDLE)
    assert [s.artifact_id for s in step_summaries] == [report_bundle_art.artifact_id]

    monkeypatch.setattr(store, "get_run_steps", lambda run_id: [run_step])
    run_summaries = reader.summarise_run_artifacts("run_1", EvidenceKind.REPORT_BUNDLE)
    assert [s.artifact_id for s in run_summaries] == [report_bundle_art.artifact_id]


def test_reader_returns_typed_advanced_reports(store) -> None:
    reader = ArtifactEvidenceReader(store)

    feature_selection_art = _register_json_artifact(
        store, "feature_selection_evidence.json", stem="feature-selection", role="report"
    )
    resampling_art = _register_json_artifact(store, "resampling_evidence.json", stem="resampling", role="report")
    tuning_art = _register_json_artifact(store, "hyperparameter_tuning_evidence.json", stem="tuning", role="report")
    explainability_art = _register_json_artifact(store, "explainability_report.json", stem="explainability", role="report")
    fairness_art = _register_json_artifact(store, "fairness_report.json", stem="fairness", role="report")
    proxy_risk_art = _register_json_artifact(store, "proxy_risk_report.json", stem="proxy-risk", role="report")

    ensemble_art = _register_inline_json_artifact(
        store,
        {
            "schema_version": "cardre.ensemble_model_artifact.v1",
            "model_family": "weighted_ensemble",
            "features": ["age", "income"],
            "target_column": "target",
            "model_payload": {
                "ensemble_type": "weighted",
                "weights": [0.6, 0.4],
                "base_models": [{"artifact_id": "m1"}, {"artifact_id": "m2"}],
            },
        },
        stem="ensemble-model",
        role="model",
        artifact_type="model",
    )

    feature_selection = reader.find([feature_selection_art], EvidenceKind.FEATURE_SELECTION_EVIDENCE)
    resampling = reader.find([resampling_art], EvidenceKind.RESAMPLING_EVIDENCE)
    tuning = reader.find([tuning_art], EvidenceKind.HYPERPARAMETER_TUNING_EVIDENCE)
    explainability = reader.find([explainability_art], EvidenceKind.EXPLAINABILITY_REPORT)
    fairness = reader.find([fairness_art], EvidenceKind.FAIRNESS_REPORT)
    proxy_risk = reader.find([proxy_risk_art], EvidenceKind.PROXY_RISK_REPORT)
    ensemble = reader.find([ensemble_art], EvidenceKind.ENSEMBLE_MODEL_ARTIFACT)

    assert isinstance(feature_selection, FeatureSelectionEvidence)
    assert feature_selection.selected[0].variable == "age"
    assert isinstance(resampling, ResamplingEvidence)
    assert resampling.synthetic_rows_added == 20
    assert isinstance(tuning, HyperparameterTuningEvidence)
    assert tuning.best_score == 0.91
    assert isinstance(explainability, ExplainabilityReport)
    assert explainability.model_family == "logistic_regression"
    assert isinstance(fairness, FairnessReport)
    assert fairness.parity_summary["gender"]["train"]["group_count"] == 2
    assert isinstance(proxy_risk, ProxyRiskReport)
    assert proxy_risk.overall_risk == "low"
    assert isinstance(ensemble, ModelArtifact)
    assert getattr(ensemble, "ensemble_type") == "weighted"
    assert getattr(ensemble, "source_artifact_id") == ensemble_art.artifact_id
