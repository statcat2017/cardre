"""Acceptance test: full Cardre pipeline with a generic (non-German Credit) CSV.

Given an arbitrary CSV with a binary target column named ``default_flag``,
Cardre can import it, profile it, define good/bad target metadata, split it,
fine-class variables, calculate WOE/IV, select variables, fit a model,
score test/OOT rows — without any German Credit-specific code path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cardre.executor import PlanExecutor
from cardre.nodes import ImportTabularDatasetNode
from cardre.registry import NodeRegistry
from cardre.services.plan_service import PlanService
from cardre.store import ProjectStore
from sidecar.proof_pathway import register_scorecard_pathway
from tests.helpers import make_synthetic_csv


@pytest.mark.e2e
class TestGenericCsvFullPipeline:
    """End-to-end pipeline using a synthetic CSV with zero German Credit references."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix="cardre_generic_e2e_"))
        self.store = ProjectStore(self._tmpdir)
        self.store.initialize()

        # Create a synthetic CSV with a binary target named default_flag
        self.source = make_synthetic_csv(self._tmpdir, filename="applications.csv", rows=200)

        # Register the Scorecard Pathway
        self.project_id = self.store.create_project("Generic E2E")
        self.plan_id = register_scorecard_pathway(self.store, self.project_id)
        self.pv_id = self.store.get_latest_plan_version_id(self.plan_id)

        yield
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _configure_and_run(self) -> str:
        """Configure import, metadata, and run the full pathway."""
        ps = PlanService(self.store)

        # 1. Configure import step with source path
        resp = ps.update_params(
            plan_id=self.plan_id, step_id="import",
            base_plan_version_id=self.pv_id,
            params={"source_path": str(self.source)},
        )
        self.pv_id = resp.new_plan_version_id

        # 2. Configure metadata with generic target (not German Credit)
        resp = ps.update_params(
            plan_id=self.plan_id, step_id="define-metadata",
            base_plan_version_id=self.pv_id,
            params={
                "target_column": "default_flag",
                "good_values": ["N"], "bad_values": ["Y"],
                "indeterminate_values": [],
            },
        )
        self.pv_id = resp.new_plan_version_id

        # 3. Update validate-target and split
        resp = ps.update_params(
            plan_id=self.plan_id, step_id="validate-target",
            base_plan_version_id=self.pv_id,
            params={"target_column": "default_flag"},
        )
        self.pv_id = resp.new_plan_version_id
        resp = ps.update_params(
            plan_id=self.plan_id, step_id="split",
            base_plan_version_id=self.pv_id,
            params={
                "strategy": "random_stratified",
                "train_fraction": 0.6, "test_fraction": 0.2, "oot_fraction": 0.2,
                "target_column": "default_flag", "role_column": None, "random_seed": 42,
            },
        )
        self.pv_id = resp.new_plan_version_id

        # 4. Lower variable-selection thresholds for small synthetic data
        resp = ps.update_params(
            plan_id=self.plan_id, step_id="variable-selection",
            base_plan_version_id=self.pv_id,
            params={"min_iv": 0.0, "max_variables": 10, "manual_includes": [], "manual_excludes": []},
        )
        self.pv_id = resp.new_plan_version_id

        # 5. Run the pathway
        reg = NodeRegistry.with_defaults()
        executor = PlanExecutor(reg)
        run_id = executor.run_plan_version(self.store, self.pv_id)
        return run_id

    def test_full_pipeline_succeeds_with_generic_csv(self):
        """The entire scorecard pathway runs to completion with synthetic data."""
        run_id = self._configure_and_run()
        run = self.store.get_run(run_id)
        assert run["status"] == "succeeded", f"Run failed: {run['status']}"

        run_steps = self.store.get_run_steps(run_id)
        step_ids = [rs.step_id for rs in run_steps]
        assert "import" in step_ids
        assert "define-metadata" in step_ids
        assert "split" in step_ids
        assert "fine-classing" in step_ids
        assert "logistic-regression" in step_ids
        assert "score-scaling" in step_ids
        assert "validation-metrics" in step_ids

    def test_no_german_credit_references_in_artifacts(self):
        """Imported artifact metadata contains no German Credit-specific fields."""
        run_id = self._configure_and_run()
        run_steps = self.store.get_run_steps(run_id)
        import_rs = [rs for rs in run_steps if rs.step_id == "import"][0]
        artifact = self.store.get_artifact(import_rs.output_artifact_ids[0])
        assert artifact is not None
        md = artifact.metadata
        assert md.get("source_file") == "applications.csv"
        assert md.get("format") == "csv"
        assert "target_column" not in md
        assert "target_mapping" not in md
        assert "source_dataset_id" not in md

    def test_import_node_is_tabular_not_german(self):
        """cardre.import_dataset resolves to ImportTabularDatasetNode."""
        reg = NodeRegistry.with_defaults()
        cls = reg.resolve("cardre.import_dataset")
        assert cls is ImportTabularDatasetNode

    def test_binary_target_mapping_uses_synthetic_values(self):
        """The modelling metadata step stores the user-supplied good/bad values."""
        run_id = self._configure_and_run()
        run_steps = self.store.get_run_steps(run_id)
        meta_rs = [rs for rs in run_steps if rs.step_id == "define-metadata"][0]
        artifact = self.store.get_artifact(meta_rs.output_artifact_ids[0])
        import json
        path = self.store.artifact_path(artifact)
        payload = json.loads(path.read_text())
        assert payload["target_column"] == "default_flag"
        assert payload["good_values"] == ["N"]
        assert payload["bad_values"] == ["Y"]
