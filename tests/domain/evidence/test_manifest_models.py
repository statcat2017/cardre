"""Manifest evidence model tests — strict schema parsing and report modes."""

from __future__ import annotations

import pytest

from cardre.domain.evidence.kinds import EvidenceParseError
from cardre.domain.evidence.models.manifest import (
    ComparisonArtifact,
    ReportBundleEvidence,
    TechnicalManifestIndex,
)
from cardre.domain.evidence.schemas import (
    SCHEMA_COMPARISON_ARTIFACT,
    SCHEMA_REPORT_BUNDLE,
    SCHEMA_TECHNICAL_MANIFEST_INDEX,
)


class TestReportBundleEvidence:
    def test_parses_branch_bundle(self):
        bundle = ReportBundleEvidence.from_json({
            "schema_version": SCHEMA_REPORT_BUNDLE,
            "project_id": "p1",
            "run_id": "r1",
            "report_mode": "branch",
        })
        assert bundle.report_mode == "branch"
        assert bundle.schema_version == SCHEMA_REPORT_BUNDLE

    def test_parses_champion_bundle(self):
        """'champion' is a supported report mode (matches the reporting system)."""
        bundle = ReportBundleEvidence.from_json({
            "schema_version": SCHEMA_REPORT_BUNDLE,
            "project_id": "p1",
            "run_id": "r1",
            "report_mode": "champion",
        })
        assert bundle.report_mode == "champion"

    def test_rejects_unknown_schema(self):
        with pytest.raises(EvidenceParseError, match="Unexpected report bundle"):
            ReportBundleEvidence.from_json({"schema_version": "cardre.report_bundle.v9"})


class TestTechnicalManifestIndex:
    def test_parses_canonical(self):
        idx = TechnicalManifestIndex.from_json({
            "schema_version": SCHEMA_TECHNICAL_MANIFEST_INDEX,
            "manifests": [{"run_id": "r1"}],
        })
        assert idx.manifests
        assert idx.schema_version == SCHEMA_TECHNICAL_MANIFEST_INDEX

    def test_rejects_unknown_schema(self):
        with pytest.raises(EvidenceParseError, match="Unexpected technical manifest"):
            TechnicalManifestIndex.from_json({
                "schema_version": "cardre.technical_manifest_index.v9",
                "manifests": [],
            })


class TestComparisonArtifact:
    def test_parses_canonical(self):
        art = ComparisonArtifact.from_json({
            "schema_version": SCHEMA_COMPARISON_ARTIFACT,
            "comparison_type": "woe_iv",
            "baseline_branch_id": "b1",
            "challenger_branch_id": "b2",
        })
        assert art.comparison_type == "woe_iv"
        assert art.schema_version == SCHEMA_COMPARISON_ARTIFACT

    def test_rejects_unknown_schema(self):
        with pytest.raises(EvidenceParseError, match="Unexpected comparison artifact"):
            ComparisonArtifact.from_json({
                "schema_version": "cardre.comparison_artifact.v9",
                "comparison_type": "woe_iv",
            })
