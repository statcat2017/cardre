"""Manifest evidence model tests — strict schema parsing."""

from __future__ import annotations

import pytest

from cardre.domain.evidence.kinds import EvidenceParseError
from cardre.domain.evidence.models.manifest import (
    ReportBundleEvidence,
    TechnicalManifestIndex,
)
from cardre.domain.evidence.schemas import (
    SCHEMA_REPORT_BUNDLE,
    SCHEMA_TECHNICAL_MANIFEST_INDEX,
)


class TestReportBundleEvidence:
    def test_parses_bundle(self):
        bundle = ReportBundleEvidence.from_json({
            "schema_version": SCHEMA_REPORT_BUNDLE,
            "project_id": "p1",
            "run_id": "r1",
        })
        assert bundle.project_id == "p1"
        assert bundle.run_id == "r1"
        assert bundle.schema_version == SCHEMA_REPORT_BUNDLE

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
