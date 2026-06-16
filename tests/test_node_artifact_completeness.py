"""Phase 0 safety-rail canary tests: every artifact written to the store
must be included in NodeOutput.artifacts.

Three nodes in prep.py call ``write_json_artifact`` for reports but discard
the return value, so the report exists in the artifact table but is NOT in
the execution fingerprint.  These tests will pass (become real failures)
once the nodes return all artifacts.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import polars as pl

from cardre.artifacts import write_parquet_artifact
from cardre.audit import (
    ArtifactRef,
    ExecutionContext,
    StepSpec,
    json_logical_hash,
    physical_hash,
    relative_path,
    table_logical_hash,
)
from cardre.nodes import (
    ApplyExclusionsNode,
    ExplicitMissingOutlierTreatmentNode,
    ImportGermanCreditNode,
    SplitTrainTestOotNode,
)
from cardre.store import ProjectStore


SAMPLE_GERMAN_CREDIT_LINES_MULTI = [
    "A11 6 A34 A43 1169 A65 A75 4 A93 A101 4 A121 67 A143 A152 2 A173 1 A192 A201 1",
    "A12 24 A32 A43 5951 A61 A73 2 A92 A101 4 A121 22 A142 A152 2 A173 1 A191 A201 2",
    "A13 12 A34 A43 2096 A61 A75 3 A93 A101 3 A121 49 A143 A152 1 A173 1 A192 A201 1",
    "A14 30 A32 A43 7882 A61 A73 4 A92 A101 2 A121 45 A142 A152 1 A173 1 A191 A201 2",
    "A15 18 A34 A43 4870 A65 A75 3 A93 A101 3 A121 53 A143 A152 2 A173 1 A192 A201 1",
    "A16 36 A32 A43 9055 A61 A73 4 A92 A101 4 A121 35 A142 A152 1 A173 1 A191 A201 2",
    "A11 9 A34 A43 1436 A65 A75 4 A93 A101 4 A121 68 A143 A152 2 A173 1 A192 A201 1",
    "A12 28 A32 A43 6798 A61 A73 2 A92 A101 4 A121 30 A142 A152 2 A173 1 A191 A201 2",
]


# ======================================================================
# Helpers
# ======================================================================


def make_store() -> tuple[ProjectStore, Path]:
    tmp = Path(tempfile.mkdtemp())
    store = ProjectStore(tmp / "test.cardre")
    store.initialize()
    return store, tmp


def make_sample_german_credit_file(tmp: Path) -> Path:
    p = tmp / "german.data"
    p.write_text("\n".join(SAMPLE_GERMAN_CREDIT_LINES_MULTI))
    return p


def import_german_credit(store: ProjectStore, tmp: Path) -> ArtifactRef:
    source = make_sample_german_credit_file(tmp)
    params = {"source_path": str(source)}
    spec = StepSpec(
        step_id="import",
        node_type="cardre.import_dataset",
        node_version="1",
        category="transform",
        params=params,
        params_hash=json_logical_hash(params),
        parent_step_ids=[],
        branch_label="",
        position=0,
    )
    ctx = ExecutionContext(
        store=store,
        run_id="r1",
        plan_version_id="pv",
        step_spec=spec,
        parent_run_steps=[],
        input_artifacts=[],
        validated_params=params,
        runtime_metadata={},
    )
    output = ImportGermanCreditNode().run(ctx)
    assert len(output.artifacts) == 1
    return output.artifacts[0]


def _make_parquet_artifact(
    store: ProjectStore,
    df: pl.DataFrame,
    role: str,
    artifact_id: str,
) -> ArtifactRef:
    buf = io.BytesIO()
    df.write_parquet(buf)
    p = store.root / "datasets" / f"{artifact_id}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(buf.getvalue())
    art = ArtifactRef(
        artifact_id=artifact_id,
        artifact_type="dataset",
        role=role,
        path=relative_path(p, store.root),
        physical_hash=physical_hash(p),
        logical_hash=table_logical_hash(df),
        media_type="application/octet-stream",
        metadata={},
    )
    store.register_artifact(art)
    return art


# ======================================================================
# Tests
# ======================================================================


class ArtifactCompletenessTests(unittest.TestCase):

    def test_split_output_includes_report(self) -> None:
        store, tmp = make_store()
        input_artifact = import_german_credit(store, tmp)

        before = len(store.list_artifacts())

        split_params = {
            "strategy": "random_stratified",
            "train_fraction": 0.6,
            "test_fraction": 0.2,
            "oot_fraction": 0.2,
            "random_seed": 42,
            "target_column": "credit_risk_class",
        }
        split_spec = StepSpec(
            step_id="split",
            node_type="cardre.split_train_test_oot",
            node_version="2",
            category="transform",
            params=split_params,
            params_hash=json_logical_hash(split_params),
            parent_step_ids=["import"],
            branch_label="",
            position=1,
        )
        split_ctx = ExecutionContext(
            store=store,
            run_id="r1",
            plan_version_id="pv",
            step_spec=split_spec,
            parent_run_steps=[],
            input_artifacts=[input_artifact],
            validated_params=split_params,
            runtime_metadata={},
        )
        split_output = SplitTrainTestOotNode().run(split_ctx)

        after = len(store.list_artifacts())
        created = after - before
        self.assertEqual(created, 4, "Split should create 3 datasets + 1 report")
        self.assertEqual(len(split_output.artifacts), created,
                         "Split NodeOutput.artifacts must include every artifact")

    def test_exclusions_output_includes_report(self) -> None:
        store, tmp = make_store()
        input_artifact = import_german_credit(store, tmp)

        before = len(store.list_artifacts())

        excl_params = {
            "rules": [
                {
                    "column": "age_years",
                    "operator": ">",
                    "value": 200,
                    "reason": "Exclude impossible ages",
                }
            ]
        }
        excl_spec = StepSpec(
            step_id="exclude",
            node_type="cardre.apply_exclusions",
            node_version="1",
            category="transform",
            params=excl_params,
            params_hash=json_logical_hash(excl_params),
            parent_step_ids=["import"],
            branch_label="",
            position=1,
        )
        excl_ctx = ExecutionContext(
            store=store,
            run_id="r1",
            plan_version_id="pv",
            step_spec=excl_spec,
            parent_run_steps=[],
            input_artifacts=[input_artifact],
            validated_params=excl_params,
            runtime_metadata={},
        )
        excl_output = ApplyExclusionsNode().run(excl_ctx)

        after = len(store.list_artifacts())
        created = after - before
        self.assertEqual(created, 2, "Exclusions should create 1 dataset + 1 report")
        self.assertEqual(len(excl_output.artifacts), created,
                         "Exclusions NodeOutput.artifacts must include every artifact")

    def test_treatment_output_includes_report(self) -> None:
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame(
            {
                "credit_risk_class": ["1", "2", "1", "2", "1", "2"],
                "duration_months": [6, 24, 12, 30, 18, 36],
                "age_years": [67, 22, 49, 45, 53, 35],
            }
        )
        train_art = _make_parquet_artifact(store, df, "train", "train-art")
        test_art = _make_parquet_artifact(store, df, "test", "test-art")
        oot_art = _make_parquet_artifact(store, df, "oot", "oot-art")

        before = len(store.list_artifacts())

        treat_params = {
            "imputations": {
                "duration_months": {"value": 0, "reason": "Fill missing durations with 0"},
            },
            "caps": {},
            "floors": {},
        }
        treat_spec = StepSpec(
            step_id="treat",
            node_type="cardre.explicit_missing_outlier_treatment",
            node_version="1",
            category="apply",
            params=treat_params,
            params_hash=json_logical_hash(treat_params),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        treat_ctx = ExecutionContext(
            store=store,
            run_id="r1",
            plan_version_id="pv",
            step_spec=treat_spec,
            parent_run_steps=[],
            input_artifacts=[train_art, test_art, oot_art],
            validated_params=treat_params,
            runtime_metadata={},
        )
        treat_output = ExplicitMissingOutlierTreatmentNode().run(treat_ctx)

        after = len(store.list_artifacts())
        created = after - before
        self.assertEqual(created, 4, "Treatment should create 3 datasets + 1 report")
        self.assertEqual(len(treat_output.artifacts), created,
                         "Treatment NodeOutput.artifacts must include every artifact")

    def test_split_output_includes_report__sanity(self) -> None:
        """Baseline: verify the split report IS written to the store."""
        store, tmp = make_store()
        input_artifact = import_german_credit(store, tmp)

        split_params = {
            "strategy": "random_stratified",
            "train_fraction": 0.6,
            "test_fraction": 0.2,
            "oot_fraction": 0.2,
            "random_seed": 42,
            "target_column": "credit_risk_class",
        }
        split_spec = StepSpec(
            step_id="split",
            node_type="cardre.split_train_test_oot",
            node_version="2",
            category="transform",
            params=split_params,
            params_hash=json_logical_hash(split_params),
            parent_step_ids=["import"],
            branch_label="",
            position=1,
        )
        split_ctx = ExecutionContext(
            store=store,
            run_id="r1",
            plan_version_id="pv",
            step_spec=split_spec,
            parent_run_steps=[],
            input_artifacts=[input_artifact],
            validated_params=split_params,
            runtime_metadata={},
        )
        split_output = SplitTrainTestOotNode().run(split_ctx)

        all_arts = store.list_artifacts()
        report_arts = [a for a in all_arts if a.artifact_type == "report"]
        output_ids = {a.artifact_id for a in split_output.artifacts}

        self.assertEqual(len(report_arts), 1, "Split should write exactly one report artifact")
        report_art = report_arts[0]
        self.assertIn(
            report_art.artifact_id,
            output_ids,
            "Report artifact must be in NodeOutput.artifacts",
        )

    def test_exclusions_output_includes_report__sanity(self) -> None:
        """Baseline: verify the exclusion report IS written to the store."""
        store, tmp = make_store()
        input_artifact = import_german_credit(store, tmp)

        excl_params = {
            "rules": [
                {
                    "column": "age_years",
                    "operator": ">",
                    "value": 200,
                    "reason": "Exclude impossible ages",
                }
            ]
        }
        excl_spec = StepSpec(
            step_id="exclude",
            node_type="cardre.apply_exclusions",
            node_version="1",
            category="transform",
            params=excl_params,
            params_hash=json_logical_hash(excl_params),
            parent_step_ids=["import"],
            branch_label="",
            position=1,
        )
        excl_ctx = ExecutionContext(
            store=store,
            run_id="r1",
            plan_version_id="pv",
            step_spec=excl_spec,
            parent_run_steps=[],
            input_artifacts=[input_artifact],
            validated_params=excl_params,
            runtime_metadata={},
        )
        excl_output = ApplyExclusionsNode().run(excl_ctx)

        all_arts = store.list_artifacts()
        report_arts = [a for a in all_arts if a.artifact_type == "report"]
        output_ids = {a.artifact_id for a in excl_output.artifacts}

        self.assertEqual(len(report_arts), 1, "Exclusions should write exactly one report artifact")
        report_art = report_arts[0]
        self.assertIn(
            report_art.artifact_id,
            output_ids,
            "Report artifact must be in NodeOutput.artifacts",
        )

    def test_treatment_output_includes_report__sanity(self) -> None:
        """Baseline: verify the treatment report IS written to the store."""
        store, tmp = make_store()
        store.initialize()

        df = pl.DataFrame(
            {
                "credit_risk_class": ["1", "2", "1", "2", "1", "2"],
                "duration_months": [6, 24, 12, 30, 18, 36],
                "age_years": [67, 22, 49, 45, 53, 35],
            }
        )
        train_art = _make_parquet_artifact(store, df, "train", "train-art")
        test_art = _make_parquet_artifact(store, df, "test", "test-art")
        oot_art = _make_parquet_artifact(store, df, "oot", "oot-art")

        treat_params = {
            "imputations": {
                "duration_months": {"value": 0, "reason": "Fill missing durations with 0"},
            },
            "caps": {},
            "floors": {},
        }
        treat_spec = StepSpec(
            step_id="treat",
            node_type="cardre.explicit_missing_outlier_treatment",
            node_version="1",
            category="apply",
            params=treat_params,
            params_hash=json_logical_hash(treat_params),
            parent_step_ids=[],
            branch_label="",
            position=0,
        )
        treat_ctx = ExecutionContext(
            store=store,
            run_id="r1",
            plan_version_id="pv",
            step_spec=treat_spec,
            parent_run_steps=[],
            input_artifacts=[train_art, test_art, oot_art],
            validated_params=treat_params,
            runtime_metadata={},
        )
        treat_output = ExplicitMissingOutlierTreatmentNode().run(treat_ctx)

        all_arts = store.list_artifacts()
        report_arts = [a for a in all_arts if a.artifact_type == "report"]
        output_ids = {a.artifact_id for a in treat_output.artifacts}

        self.assertEqual(len(report_arts), 1, "Treatment should write exactly one report artifact")
        report_art = report_arts[0]
        self.assertIn(
            report_art.artifact_id,
            output_ids,
            "Report artifact must be in NodeOutput.artifacts",
        )


if __name__ == "__main__":
    unittest.main()
