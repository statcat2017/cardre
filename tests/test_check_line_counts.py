"""Tests for scripts/check-line-counts.py — three-bucket policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-line-counts.py"

LANGUAGE_NORMAL_THRESHOLDS = {"python": 1000, "typescript": 600, "rust": 300}


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("check_line_counts", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── filter_policy_files ──────────────────────────────────────────────


class TestFilterPolicyFiles:
    def test_removes_generated_files(self, mod):
        result = mod.filter_policy_files([
            "cardre/__init__.py",
            "frontend/src/api/schema.d.ts",
        ])
        assert "frontend/src/api/schema.d.ts" not in result
        assert result == ["cardre/__init__.py"]


# ── check_policy_health ──────────────────────────────────────────────


class TestPolicyHealth:
    def test_returns_no_issues_for_current_constants(self, mod):
        """All policy entries should point to real files with no
        cross-bucket overlap."""
        issues = mod.check_policy_health()
        assert issues == [], f"Policy health issues: {issues}"

    def test_no_bucket_overlap(self, mod):
        paths: dict[str, list[str]] = {}
        for p in mod.GENERATED_FILES:
            paths.setdefault(p, []).append("GENERATED_FILES")
        for p in mod.SEAM_WATCHLIST:
            paths.setdefault(p, []).append("SEAM_WATCHLIST")
        for p in mod.LINE_COUNT_DEBT:
            paths.setdefault(p, []).append("LINE_COUNT_DEBT")
        duplicates = {p: b for p, b in paths.items() if len(b) > 1}
        assert duplicates == {}, f"Paths in multiple buckets: {duplicates}"


# ── Normal files ─────────────────────────────────────────────────────


class TestNormalFiles:
    def test_under_threshold(self, mod):
        counts = {"cardre/some_file.py": 500}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_over_threshold(self, mod):
        counts = {"cardre/some_file.py": 1500}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        assert v[0][0] == "cardre/some_file.py"
        assert v[0][1] == 1500
        assert v[0][2] == 1000
        assert v[0][3] == ""
        assert sw == []
        assert sd == []

    def test_exactly_at_threshold(self, mod):
        counts = {"cardre/some_file.py": 1000}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_typescript_over_threshold(self, mod):
        counts = {"frontend/src/SomeComponent.tsx": 800}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        assert v[0][0] == "frontend/src/SomeComponent.tsx"
        assert v[0][2] == 600

    def test_rust_over_threshold(self, mod):
        counts = {"frontend/src-tauri/src/something.rs": 500}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        assert v[0][2] == 300


# ── Generated files ──────────────────────────────────────────────────


class TestGeneratedFiles:
    def test_generated_in_constant(self, mod):
        assert "frontend/src/api/schema.d.ts" in mod.GENERATED_FILES

    def test_generated_excluded_by_filter(self, mod):
        files = ["frontend/src/api/schema.d.ts", "cardre/__init__.py"]
        result = mod.filter_policy_files(files)
        assert "frontend/src/api/schema.d.ts" not in result
        assert "cardre/__init__.py" in result


# ── Seam watchlist ───────────────────────────────────────────────────


class TestSeamWatchlist:
    def test_under_normal_threshold_silent(self, mod):
        counts = {"cardre/executor.py": 500}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_between_normal_and_seam_emits_warning(self, mod):
        counts = {"cardre/executor.py": 1200}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert len(sw) == 1
        fpath, count, norm_threshold, owner = sw[0]
        assert fpath == "cardre/executor.py"
        assert count == 1200
        assert norm_threshold == 1000
        assert owner == "execution seam"

    def test_over_seam_threshold_violates(self, mod):
        counts = {"cardre/executor.py": 1500}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        fpath, count, seam_threshold, tag = v[0]
        assert fpath == "cardre/executor.py"
        assert count == 1500
        assert seam_threshold == 1400
        assert tag == "seam:execution seam"
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
            assert isinstance(info["split_only_on"], list), (
                f"{fpath} split_only_on not a list"
            )
            assert len(info["split_only_on"]) > 0, (
                f"{fpath} has empty split_only_on"
            )

            lang = mod.classify_file(fpath)
            assert lang is not None, f"{fpath} has unrecognised extension"
            normal = LANGUAGE_NORMAL_THRESHOLDS.get(lang, 0)
            assert info["threshold"] > normal, (
                f"{fpath} seam threshold {info['threshold']} is not above "
                f"its language's normal threshold {normal} (lang={lang})"
            )


# ── Line-count debt ──────────────────────────────────────────────────


class TestLineCountDebt:
    def test_debt_file_below_ceiling_allowed(self, mod):
        counts = {"cardre/_evidence/models.py": 1116}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_debt_file_under_threshold_is_stale(self, mod):
        counts = {"cardre/_evidence/models.py": 500}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == ["cardre/_evidence/models.py"]

    def test_debt_file_above_ceiling_violates(self, mod):
        counts = {"cardre/_evidence/models.py": 9999}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        fpath, count, ceiling, tag = v[0]
        assert fpath == "cardre/_evidence/models.py"
        assert count == 9999
        assert ceiling == 1300
        assert tag == "debt:cardre/_evidence/models.py"
        assert sd == []

    def test_all_debt_entries_have_required_keys(self, mod):
        for fpath, info in mod.LINE_COUNT_DEBT.items():
            assert "current_count" in info, f"{fpath} missing current_count"
            assert "ceiling" in info, f"{fpath} missing ceiling"
            assert "reason" in info, f"{fpath} missing reason"
            assert info["ceiling"] >= info["current_count"], (
                f"{fpath} ceiling {info['ceiling']} is below "
                f"current_count {info['current_count']}"
            )
            assert info["ceiling"] > LANGUAGE_NORMAL_THRESHOLDS["python"], (
                f"{fpath} ceiling {info['ceiling']} is not above "
                f"Python normal threshold {LANGUAGE_NORMAL_THRESHOLDS['python']}"
            )

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


# ── Unrecognised extensions ──────────────────────────────────────────


class TestUnrecognizedExtension:
    def test_unknown_extension_skipped(self, mod):
        counts = {"some_file.xyz": 5000}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_no_extension_skipped(self, mod):
        counts = {"Makefile": 5000}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_counts(self, mod):
        v, sw, sd = mod.check_line_counts({}, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_debt_exact_at_ceiling(self, mod):
        counts = {"cardre/_evidence/models.py": 1300}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert sw == []
        assert sd == []

    def test_debt_just_above_ceiling(self, mod):
        counts = {"cardre/_evidence/models.py": 1301}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        assert v[0][2] == 1300
        assert v[0][3].startswith("debt:")

    def test_seam_exact_at_seam_threshold(self, mod):
        counts = {"cardre/executor.py": 1400}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert v == []
        assert len(sw) == 1
        assert sw[0][0] == "cardre/executor.py"
        assert sw[0][1] == 1400

    def test_seam_just_above_seam_threshold(self, mod):
        counts = {"cardre/executor.py": 1401}
        v, sw, sd = mod.check_line_counts(counts, LANGUAGE_NORMAL_THRESHOLDS)
        assert len(v) == 1
        assert v[0][2] == 1400
        assert v[0][3] == "seam:execution seam"
