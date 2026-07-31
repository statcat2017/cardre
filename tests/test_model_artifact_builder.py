from __future__ import annotations

from types import SimpleNamespace

from cardre.modeling.builders import build_model_artifact


def test_build_model_artifact_references_staged_estimator_with_explicit_ids():
    estimator_artifact = SimpleNamespace(
        provisional_artifact_id="estimator-artifact",
        logical_hash="logical-hash",
        physical_hash="physical-hash",
    )

    model = build_model_artifact(
        model_family="decision_tree",
        target_column="target",
        features=["feature"],
        bad_class="bad",
        good_class="good",
        prob_col_idx=1,
        feature_strategy="raw_numeric",
        estimator_art=estimator_artifact,
        training_params={},
        random_seed=42,
        elapsed=0.1,
        model_payload={},
        interpretability={},
        run_id="run-1",
        step_id="fit-1",
    )

    assert model["estimator_reference"] == {
        "artifact_id": "estimator-artifact",
        "logical_hash": "logical-hash",
        "physical_hash": "physical-hash",
        "estimator_format": "joblib",
        "trusted_load_required": True,
        "creating_run_id": "run-1",
        "creating_run_step_id": "fit-1",
    }
