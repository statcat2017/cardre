"""Contract tests for the deep model-Artifact publication/load module.

Two tiers, per the design decision:

- **Tier-1** (pure fakes, no I/O): pin the publish ordering invariant and the
  ref computation — the JSON model is published before the binary is staged,
  and the descriptor id the ref carries matches the id the store assigns.
- **Tier-2** (real store): pin the round-trip — ``publish_estimator`` →
  ``stage_estimator_bytes`` → finalize → read back → ``load_estimator``
  deserialises the exact estimator that was published, and refuses tampered or
  unprovenanced binaries (ADR-0016).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from node_harness import FakeArtifact, FakeInputCollection, FakeOutputPublisher
from sklearn.linear_model import LogisticRegression

from cardre.adapters.evidence.reader import EvidenceReader
from cardre.adapters.filesystem.artifact_store import FsArtifactStore
from cardre.application.execution.input_collection import StepInputCollection
from cardre.application.execution.output_publisher import StagingOutputPublisher
from cardre.domain.artifacts import ArtifactRef
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes._model_artifacts import (
    EstimatorRef,
    estimator_descriptor_id,
    load_estimator,
    publish_estimator,
    stage_estimator_bytes,
)
from cardre.nodes._samples import SAMPLE_ROLES, sample_bundle

MODEL_FAMILY = "logistic_regression"


def _fitted():
    est = LogisticRegression(solver="liblinear")
    est.fit([[1.0], [2.0], [3.0]], [0, 1, 0])
    return est


def _to_ref(staged) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=staged.provisional_artifact_id,
        artifact_type=staged.artifact_type,
        role=staged.role,
        path=str(staged.staging_path),
        physical_hash=staged.physical_hash,
        logical_hash=staged.logical_hash,
        media_type=staged.media_type,
        metadata=staged.metadata,
    )


# ---------------------------------------------------------------------------
# Tier-1: publish ordering + ref computation against the fake publisher
# ---------------------------------------------------------------------------


class TestPublishOrderingAndRef:
    def test_ref_matches_store_descriptor_id(self):
        est = _fitted()
        ref = publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
        )

        # The ref must carry the same descriptor id the store derives at stage
        # time, so the JSON model can cite it before the binary is staged.
        assert isinstance(ref, EstimatorRef)
        assert ref.provisional_artifact_id == estimator_descriptor_id(
            ref.bytes, ref.logical_hash, ref.metadata,
        )
        assert ref.physical_hash == ref.logical_hash == hashlib.sha256(ref.bytes).hexdigest()

    def test_stage_estimator_bytes_publishes_under_estimator_role(self):
        est = _fitted()
        outputs = FakeOutputPublisher()
        ref = publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
        )
        staged = stage_estimator_bytes(outputs, ref)

        assert staged.role == "estimator"
        assert staged.media_type == "application/octet-stream"
        assert staged.data == ref.bytes
        assert staged.logical_hash == ref.logical_hash

    def test_publish_does_not_stage(self):
        """publish_estimator only returns a ref; the binary is staged by an
        explicit stage_estimator_bytes call so the JSON model is published
        first."""
        est = _fitted()
        outputs = FakeOutputPublisher()
        publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
        )
        assert outputs.staged == []
        assert outputs.by_role("estimator") == []

    def test_metadata_merge_preserves_provenance_and_subtype(self):
        est = _fitted()
        ref = publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
            metadata={"artifact_subtype": "probability_calibrator", "method": "platt"},
        )
        assert ref.metadata["creating_run_id"] == "run-1"
        assert ref.metadata["creating_run_step_id"] == "fit-1"
        assert ref.metadata["artifact_subtype"] == "probability_calibrator"
        assert ref.metadata["method"] == "platt"
        assert ref.metadata["estimator_format"] == "joblib"


# ---------------------------------------------------------------------------
# Tier-2: round-trip through the real store
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_publish_finalize_load_roundtrip(self, tmp_path: Path):
        store = FsArtifactStore(tmp_path)
        pub = StagingOutputPublisher(store)
        est = _fitted()

        ref = publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
        )
        # The JSON model is published first (citing the pre-staged descriptor id).
        model_staged = pub.publish_json(
            role="model",
            kind=EvidenceKind.MODEL_ARTIFACT,
            payload={
                "schema_version": "cardre.model_artifact.v1",
                "model_family": MODEL_FAMILY,
                "estimator_reference": {
                    "artifact_id": ref.provisional_artifact_id,
                    "logical_hash": ref.logical_hash,
                    "physical_hash": ref.physical_hash,
                },
            },
            metadata={"schema_version": "cardre.model_artifact.v1"},
        )
        binary_staged = stage_estimator_bytes(pub, ref)

        # The JSON model's estimator_reference must equal the staged binary id.
        assert model_staged.media_type == "application/json"
        assert binary_staged.provisional_artifact_id == ref.provisional_artifact_id

        for staged in (model_staged, binary_staged):
            store.finalize(staged)

        reader = EvidenceReader(store, _NullRepo(), _NullRepo())
        inputs = StepInputCollection(reader, [_to_ref(model_staged), _to_ref(binary_staged)])

        loaded = load_estimator(
            inputs,
            {
                "artifact_id": ref.provisional_artifact_id,
                "logical_hash": ref.logical_hash,
                "physical_hash": ref.physical_hash,
            },
            node_type="test",
        )
        assert loaded is not None
        assert isinstance(loaded, LogisticRegression)
        assert loaded.get_params() == est.get_params()


class _NullRepo:
    def get(self, artifact_id):
        return None


class TestMandatoryVerification:
    def test_refuses_tampered_bytes(self):
        est = _fitted()
        outputs = FakeOutputPublisher()
        ref = publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
        )
        staged = stage_estimator_bytes(outputs, ref)

        # Tamper: publish different bytes under the same ref.
        tampered = ref.bytes + b"X"
        tampered_art = _art(role="estimator", artifact_id=staged.artifact_id,
                            logical_hash=ref.logical_hash, data=tampered)
        inputs = FakeInputCollection(roles={"estimator": [tampered_art]},
                                     bytes_by_id={tampered_art.artifact_id: tampered})

        with pytest.raises(ValueError, match="hash mismatch"):
            load_estimator(
                inputs,
                {"artifact_id": staged.artifact_id, "logical_hash": ref.logical_hash},
                node_type="test",
            )

    def test_refuses_binary_without_provenance(self):
        raw = b"whatever-bytes"
        no_provenance = FakeArtifact(
            role="estimator", artifact_id="est-1",
            metadata={},  # no creating_run_id
        )
        inputs = FakeInputCollection(
            roles={"estimator": [no_provenance]},
            bytes_by_id={"est-1": raw},
        )
        with pytest.raises(ValueError, match="creating_run_id"):
            load_estimator(
                inputs, {"artifact_id": "est-1", "logical_hash": hashlib.sha256(raw).hexdigest()},
                node_type="test",
            )

    def test_returns_none_when_no_reference_or_missing_artifact(self):
        est = _fitted()
        ref = publish_estimator(
            est, step_id="fit-1", run_id="run-1", model_family=MODEL_FAMILY,
        )
        inputs = FakeInputCollection()
        assert load_estimator(inputs, {}, node_type="test") is None
        assert load_estimator(
            inputs, {"artifact_id": ref.provisional_artifact_id}, node_type="test",
        ) is None


# ---------------------------------------------------------------------------
# sample_bundle helper
# ---------------------------------------------------------------------------


class TestSampleBundle:
    def test_collects_train_test_oot_in_order(self):
        roles = {
            "train": [_art("train"), _art("train")],
            "test": [_art("test")],
            "oot": [_art("oot")],
        }
        inputs = FakeInputCollection(roles=roles)
        bundle = sample_bundle(inputs)
        assert [a.role for a in bundle] == ["train", "train", "test", "oot"]
        assert SAMPLE_ROLES == ("train", "test", "oot")

    def test_empty_roles_yield_empty_bundle(self):
        inputs = FakeInputCollection()
        assert sample_bundle(inputs) == []


def _art(role: str, artifact_id: str | None = None, data: bytes | None = None,
         logical_hash: str = "log"):
    return FakeArtifact(role=role, artifact_id=artifact_id, data=data)
