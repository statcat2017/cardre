"""Tests for scripts/check-line-counts.py — three-bucket policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-line-counts.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("check_line_counts", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


THRESHOLDS = {"python": 1000, "typescript": 600, "rust": 300}


class TestNormalFiles:
    def test_under_threshold(self, mod):
        counts = {"cardre/some_file.py": 500}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_over_threshold(self, mod):
        counts = {"cardre/some_file.py": 1500}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert len(v) == 1
        assert v[0][0] == "cardre/some_file.py"
        assert v[0][1] == 1500
        assert v[0][2] == 1000
        assert v[0][3] == ""
        assert sw == []
        assert sd == []

    def test_exactly_at_threshold(self, mod):
        counts = {"cardre/some_file.py": 1000}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_typescript_over_threshold(self, mod):
        counts = {"frontend/src/SomeComponent.tsx": 800}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert len(v) == 1
        assert v[0][0] == "frontend/src/SomeComponent.tsx"
        assert v[0][2] == 600

    def test_rust_over_threshold(self, mod):
        counts = {"frontend/src-tauri/src/something.rs": 500}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert len(v) == 1
        assert v[0][2] == 300


class TestGeneratedFiles:
    def test_generated_in_constant(self, mod):
        assert "frontend/src/api/schema.d.ts" in mod.GENERATED_FILES


class TestSeamWatchlist:
    def test_under_normal_threshold_silent(self, mod):
        counts = {"cardre/executor.py": 500}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_between_normal_and_seam_emits_warning(self, mod):
        counts = {"cardre/executor.py": 1200}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert len(sw) == 1
        fpath, count, norm_threshold, owner = sw[0]
        assert fpath == "cardre/executor.py"
        assert count == 1200
        assert norm_threshold == 1000
        assert owner == "execution seam"

    def test_over_seam_threshold_violates(self, mod):
        counts = {"cardre/executor.py": 1500}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert len(v) == 1
        fpath, count, seam_threshold, owner = v[0]
        assert fpath == "cardre/executor.py"
        assert count == 1500
        assert seam_threshold == 1400
        assert owner == "execution seam"
        assert sw == []

    def test_project_store_seam(self, mod):
        seam = mod.SEAM_WATCHLIST["cardre/store/project_store.py"]
        assert seam["threshold"] == 1400
        assert seam["owner"] == "ProjectStore compatibility facade"

    def test_collector_seam(self, mod):
        seam = mod.SEAM_WATCHLIST["cardre/reporting/collector.py"]
        assert seam["threshold"] == 1400

    def test_comparison_service_seam(self, mod):
        seam = mod.SEAM_WATCHLIST["cardre/services/comparison_service.py"]
        assert seam["threshold"] == 1200

    def test_modeling_adapters_seam(self, mod):
        seam = mod.SEAM_WATCHLIST["cardre/modeling/adapters.py"]
        assert seam["threshold"] == 1400

    def test_all_seam_entries_have_required_keys(self, mod):
        for fpath, info in mod.SEAM_WATCHLIST.items():
            assert "threshold" in info, f"{fpath} missing threshold"
            assert "owner" in info, f"{fpath} missing owner"
            assert "split_only_on" in info, f"{fpath} missing split_only_on"
            assert isinstance(info["split_only_on"], list), f"{fpath} split_only_on not a list"
            assert len(info["split_only_on"]) > 0, f"{fpath} has empty split_only_on"
            assert info["threshold"] > THRESHOLDS["python"], (
                f"{fpath} seam threshold {info['threshold']} is not above "
                f"Python normal threshold {THRESHOLDS['python']}"
            )


class TestLineCountDebt:
    def test_debt_file_over_threshold_exempt(self, mod):
        counts = {"cardre/_evidence/models.py": 1116}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_debt_file_under_threshold_is_stale(self, mod):
        counts = {"cardre/_evidence/models.py": 500}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == ["cardre/_evidence/models.py"]

    def test_all_debt_entries_listed(self, mod):
        expected = {
            "cardre/_evidence/models.py",
            "cardre/nodes/prep.py",
            "tests/test_sidecar_api.py",
            "tests/test_optbinning.py",
            "tests/test_bin_definition_lifecycle.py",
            "tests/test_nodes.py",
            "tests/test_reporting.py",
        }
        assert set(mod.LINE_COUNT_DEBT.keys()) == expected


class TestUnrecognizedExtension:
    def test_unknown_extension_skipped(self, mod):
        counts = {"some_file.xyz": 5000}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_no_extension_skipped(self, mod):
        counts = {"Makefile": 5000}
        v, sw, sd = mod.check_line_counts(counts, THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []
