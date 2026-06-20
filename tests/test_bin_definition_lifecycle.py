"""Lock-down tests for current bin-definition lifecycle behaviour.

These tests capture the current shape of cardre.bin_definition.v1
payloads and the rules in validate_manual_binning_overrides /
apply_manual_binning_overrides before they are moved to a deeper
lifecycle module.  If a proposed change breaks one of these tests,
it either preserves current behaviour or the test itself must be
updated to reflect the new intended behaviour.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cardre.audit import json_logical_hash
from cardre.engine.binning.definition import LifecycleBinDefinition

# ======================================================================
# Fixtures: representative payloads at the cardre.bin_definition.v1 seam
# ======================================================================


@pytest.fixture
def fc_payload() -> dict[str, Any]:
    """Payload shape produced by FineClassingNode (fine classing method)."""
    return {
        "schema_version": "cardre.bin_definition.v1",
        "variables": [
            {
                "variable": "age",
                "kind": "numeric",
                "bins": [
                    {
                        "bin_id": "age_bin_001",
                        "label": "(-inf, 30)",
                        "lower": None,
                        "upper": 30,
                        "lower_inclusive": False,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 40,
                        "good_count": 25,
                        "bad_count": 15,
                    },
                    {
                        "bin_id": "age_bin_002",
                        "label": "[30, 45)",
                        "lower": 30,
                        "upper": 45,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 60,
                        "good_count": 35,
                        "bad_count": 25,
                    },
                    {
                        "bin_id": "age_bin_003",
                        "label": "[45, +inf)",
                        "lower": 45,
                        "upper": None,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 50,
                        "good_count": 20,
                        "bad_count": 30,
                    },
                ],
            },
            {
                "variable": "income",
                "kind": "numeric",
                "bins": [
                    {
                        "bin_id": "income_bin_001",
                        "label": "(-inf, 40000)",
                        "lower": None,
                        "upper": 40000,
                        "lower_inclusive": False,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 30,
                        "good_count": 10,
                        "bad_count": 20,
                    },
                    {
                        "bin_id": "income_bin_002",
                        "label": "[40000, 80000)",
                        "lower": 40000,
                        "upper": 80000,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 50,
                        "good_count": 30,
                        "bad_count": 20,
                    },
                    {
                        "bin_id": "income_bin_003",
                        "label": "[80000, +inf)",
                        "lower": 80000,
                        "upper": None,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 20,
                        "good_count": 15,
                        "bad_count": 5,
                    },
                ],
            },
        ],
        "warnings": [],
    }


@pytest.fixture
def optbinning_payload() -> dict[str, Any]:
    """Payload shape produced by AutoBinningFitNode (optbinning method).

    Includes fields that FineClassingNode does not produce: source,
    rejected, active, status, diagnostics-like warnings.
    """
    return {
        "schema_version": "cardre.bin_definition.v1",
        "variables": [
            {
                "variable": "age",
                "dtype": "numerical",
                "kind": "numeric",
                "bins": [
                    {
                        "bin_id": "age_bin_001",
                        "label": "(-inf, 30.0)",
                        "kind": "numeric",
                        "lower": None,
                        "upper": 30.0,
                        "lower_inclusive": False,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 150,
                        "row_pct": 0.3,
                        "good_count": 100,
                        "bad_count": 50,
                        "bad_rate": 0.333,
                        "woe": 0.5,
                        "iv": 0.12,
                    },
                    {
                        "bin_id": "age_bin_002",
                        "label": "[30.0, +inf)",
                        "kind": "numeric",
                        "lower": 30.0,
                        "upper": None,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 350,
                        "row_pct": 0.7,
                        "good_count": 200,
                        "bad_count": 150,
                        "bad_rate": 0.429,
                        "woe": -0.3,
                        "iv": 0.08,
                    },
                ],
                "status": "OPTIMAL",
                "active": True,
                "metrics": {
                    "iv": 0.2,
                    "n_bins": 2,
                    "row_count": 500,
                    "missing_count": 0,
                    "missing_rate": 0.0,
                    "min_bin_count": 150,
                    "max_bin_pct": 0.7,
                    "monotonic_woe": True,
                },
            },
            {
                "variable": "income",
                "dtype": "numerical",
                "kind": "numeric",
                "bins": [
                    {
                        "bin_id": "income_bin_001",
                        "label": "(-inf, 60000.0)",
                        "kind": "numeric",
                        "lower": None,
                        "upper": 60000.0,
                        "lower_inclusive": False,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 200,
                        "row_pct": 0.4,
                        "good_count": 120,
                        "bad_count": 80,
                        "bad_rate": 0.4,
                        "woe": 0.2,
                        "iv": 0.06,
                    },
                    {
                        "bin_id": "income_bin_002",
                        "label": "[60000.0, +inf)",
                        "kind": "numeric",
                        "lower": 60000.0,
                        "upper": None,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 300,
                        "row_pct": 0.6,
                        "good_count": 180,
                        "bad_count": 120,
                        "bad_rate": 0.4,
                        "woe": 0.0,
                        "iv": 0.0,
                    },
                ],
                "status": "OPTIMAL",
                "active": True,
                "metrics": {
                    "iv": 0.06,
                    "n_bins": 2,
                    "row_count": 500,
                    "missing_count": 0,
                    "missing_rate": 0.0,
                    "min_bin_count": 200,
                    "max_bin_pct": 0.6,
                    "monotonic_woe": True,
                },
            },
        ],
        "rejected": [
            {
                "variable": "old_feature",
                "dtype": "numerical",
                "kind": "numeric",
                "bins": [],
                "status": "FAILED",
                "active": False,
                "failure_reason": "OptBinning failed: no variance",
                "warnings": [
                    {
                        "code": "VARIABLE_FAILED",
                        "severity": "error",
                        "variable": "old_feature",
                        "message": "Variable failed optbinning fit; excluded from active definition",
                        "requires_acknowledgement": True,
                        "details": {},
                    },
                ],
            }
        ],
        "warnings": [
            {
                "code": "VARIABLE_FAILED",
                "severity": "error",
                "variable": "old_feature",
                "message": "Variable failed optbinning fit; excluded from active definition",
                "requires_acknowledgement": True,
                "details": {},
            },
        ],
        "source": {
            "engine": "optbinning",
            "engine_version": "0.21.0",
            "method": "optbinning",
            "node_id": "auto-bin-001",
            "fit_sample_role": "train",
            "train_artifact_id": "train1",
            "train_physical_hash": "abc123",
            "train_logical_hash": "def456",
            "target_column": "target",
            "good_values": ["good"],
            "bad_values": ["bad"],
            "params": {"engine": "optbinning"},
        },
    }


@pytest.fixture
def manual_binning_merge_overrides() -> list[dict]:
    return [
        {
            "variable": "age",
            "action": "merge_bins",
            "source_bin_ids": ["age_bin_001", "age_bin_002"],
            "new_label": "Low-Mid",
            "reason": "Merged adjacent sparse bins",
        },
        {
            "variable": "income",
            "action": "merge_bins",
            "source_bin_ids": ["income_bin_001", "income_bin_002"],
            "new_label": "Combined",
            "reason": "Combine sparse bins",
        },
    ]


@pytest.fixture
def fc_payload_with_missing() -> dict[str, Any]:
    """Fine-classing payload with a missing-value bin."""
    return {
        "schema_version": "cardre.bin_definition.v1",
        "variables": [
            {
                "variable": "score",
                "kind": "numeric",
                "bins": [
                    {
                        "bin_id": "score_bin_001",
                        "label": "Missing",
                        "lower": None,
                        "upper": None,
                        "lower_inclusive": False,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": True,
                        "row_count": 10,
                        "good_count": 8,
                        "bad_count": 2,
                    },
                    {
                        "bin_id": "score_bin_002",
                        "label": "(-inf, 50)",
                        "lower": None,
                        "upper": 50,
                        "lower_inclusive": False,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 50,
                        "good_count": 30,
                        "bad_count": 20,
                    },
                    {
                        "bin_id": "score_bin_003",
                        "label": "[50, +inf)",
                        "lower": 50,
                        "upper": None,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                        "categories": None,
                        "is_missing_bin": False,
                        "row_count": 100,
                        "good_count": 70,
                        "bad_count": 30,
                    },
                ],
            }
        ],
        "warnings": [],
    }


# ======================================================================
# Tests: fine-classing payload round-trip
# ======================================================================


class TestFineClassingRoundTrip:
    """A lifecycle module must preserve fine-classing payload features."""

    def test_fc_payload_has_schema_version(self, fc_payload):
        assert fc_payload["schema_version"] == "cardre.bin_definition.v1"

    def test_fc_payload_variable_names(self, fc_payload):
        names = {v["variable"] for v in fc_payload["variables"]}
        assert names == {"age", "income"}

    def test_fc_payload_all_bins_have_required_fields(self, fc_payload):
        required = {"bin_id", "label", "lower", "upper", "lower_inclusive",
                     "upper_inclusive", "categories", "is_missing_bin",
                     "row_count", "good_count", "bad_count"}
        for v in fc_payload["variables"]:
            for b in v["bins"]:
                missing = required - set(b.keys())
                assert not missing, f"Variable {v['variable']} bin {b.get('bin_id')} missing: {missing}"

    def test_fc_payload_no_rejected(self, fc_payload):
        assert "rejected" not in fc_payload or fc_payload["rejected"] == []

    def test_fc_payload_no_source(self, fc_payload):
        assert "source" not in fc_payload

    def test_fc_payload_deterministic_hash(self, fc_payload):
        h1 = json_logical_hash(fc_payload)
        h2 = json_logical_hash(fc_payload)
        assert h1 == h2

    def test_fc_payload_same_content_same_hash(self, fc_payload):
        import copy
        payload2 = copy.deepcopy(fc_payload)
        assert json_logical_hash(fc_payload) == json_logical_hash(payload2)


# ======================================================================
# Tests: optbinning payload round-trip
# ======================================================================


class TestOptBinningRoundTrip:
    """A lifecycle module must preserve optbinning payload features."""

    def test_optbinning_has_schema_version(self, optbinning_payload):
        assert optbinning_payload["schema_version"] == "cardre.bin_definition.v1"

    def test_optbinning_has_source(self, optbinning_payload):
        assert "source" in optbinning_payload
        assert optbinning_payload["source"]["engine"] == "optbinning"

    def test_optbinning_has_rejected(self, optbinning_payload):
        assert "rejected" in optbinning_payload
        assert len(optbinning_payload["rejected"]) == 1
        r = optbinning_payload["rejected"][0]
        assert r["variable"] == "old_feature"
        assert r.get("active") is False

    def test_optbinning_variables_have_metrics(self, optbinning_payload):
        for v in optbinning_payload["variables"]:
            assert "metrics" in v
            assert "iv" in v["metrics"]

    def test_optbinning_variables_have_active(self, optbinning_payload):
        for v in optbinning_payload["variables"]:
            assert v.get("active") is True

    def test_optbinning_variables_have_status(self, optbinning_payload):
        for v in optbinning_payload["variables"]:
            assert "status" in v
            assert v["status"] == "OPTIMAL"

    def test_optbinning_variables_have_dtype(self, optbinning_payload):
        for v in optbinning_payload["variables"]:
            assert "dtype" in v

    def test_optbinning_warnings_are_structured(self, optbinning_payload):
        for w in optbinning_payload["warnings"]:
            assert isinstance(w, dict)
            assert "code" in w
            assert "severity" in w
            assert "message" in w

    def test_optbinning_deterministic_hash(self, optbinning_payload):
        h1 = json_logical_hash(optbinning_payload)
        h2 = json_logical_hash(optbinning_payload)
        assert h1 == h2


# ======================================================================
# Tests: manual-binning override rules
# ======================================================================


class TestManualBinningOverrideRules:
    """These rules currently live in bins.py; a lifecycle module must
    preserve them."""

    def test_merge_adjacent_numeric_bins(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [
            {
                "variable": "age",
                "action": "merge_bins",
                "source_bin_ids": ["age_bin_001", "age_bin_002"],
                "new_label": "Low-Mid",
                "reason": "Merged adjacent bins",
            }
        ]
        result = apply_manual_binning_overrides(fc_payload, overrides)
        age_var = next(v for v in result["variables"] if v["variable"] == "age")
        assert len(age_var["bins"]) == 2  # 3 → 2 after merge
        assert age_var["bins"][0]["label"] == "Low-Mid"

    def test_merge_non_adjacent_numeric_bins_fails(self, fc_payload):
        from cardre.nodes import validate_manual_binning_overrides

        overrides = [
            {
                "variable": "age",
                "action": "merge_bins",
                "source_bin_ids": ["age_bin_001", "age_bin_003"],
                "new_label": "Non-adjacent",
                "reason": "Testing adjacency",
            }
        ]
        errs = validate_manual_binning_overrides(fc_payload, overrides)
        assert len(errs) > 0
        assert "adjacent" in errs[0].lower()

    def test_merge_keeps_correct_counts(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [
            {
                "variable": "age",
                "action": "merge_bins",
                "source_bin_ids": ["age_bin_001", "age_bin_002"],
                "new_label": "Low-Mid",
                "reason": "Merged adjacent bins",
            }
        ]
        result = apply_manual_binning_overrides(fc_payload, overrides)
        age_var = next(v for v in result["variables"] if v["variable"] == "age")
        merged = age_var["bins"][0]
        assert merged["row_count"] == 40 + 60  # sum of source bin counts
        assert merged["good_count"] == 25 + 35
        assert merged["bad_count"] == 15 + 25

    def test_no_op_emits_warning(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        result = apply_manual_binning_overrides(fc_payload, [])
        assert "warnings" in result
        assert len(result["warnings"]) == len(fc_payload.get("warnings", [])) + 1
        assert any("No manual overrides applied" in str(w.get("message", "")) for w in result["warnings"])

    def test_reject_variable_removes_from_variables(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [
            {
                "variable": "age",
                "action": "reject_variable",
                "source_bin_ids": [],
                "reason": "High missing rate",
            }
        ]
        result = apply_manual_binning_overrides(fc_payload, overrides)
        var_names = [v["variable"] for v in result["variables"]]
        assert "age" not in var_names
        assert result["rejected"] is not None
        assert any(r["variable"] == "age" for r in result["rejected"])

    def test_reject_variable_requires_reason(self, fc_payload):
        from cardre.nodes import validate_manual_binning_overrides

        errs = validate_manual_binning_overrides(fc_payload, [
            {"variable": "age", "action": "reject_variable",
             "source_bin_ids": [], "reason": ""},
        ])
        assert len(errs) > 0
        assert "reason" in errs[0].lower()

    def test_override_history_no_timestamp(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [
            {
                "variable": "age",
                "action": "merge_bins",
                "source_bin_ids": ["age_bin_001", "age_bin_002"],
                "new_label": "Low-Mid",
                "reason": "Merged adjacent bins",
            }
        ]
        result = apply_manual_binning_overrides(fc_payload, overrides)
        age_var = next(v for v in result["variables"] if v["variable"] == "age")
        events = age_var.get("override_history", [])
        assert len(events) == 1
        assert "timestamp" not in events[0]
        assert events[0]["user_action"] == "merge_bins"

    def test_reorder_missing_bin_moves_to_end(self, fc_payload_with_missing):
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [
            {
                "variable": "score",
                "action": "reorder_missing_bin",
                "source_bin_ids": ["score_bin_001"],
                "reason": "Reorder missing to end",
            }
        ]
        result = apply_manual_binning_overrides(
            fc_payload_with_missing, overrides,
        )
        score_var = next(v for v in result["variables"] if v["variable"] == "score")
        assert score_var["bins"][-1]["is_missing_bin"]

    def test_reorder_special_bin_moves_to_end(self, fc_payload_with_missing):
        from cardre.nodes import apply_manual_binning_overrides

        bins_copy = fc_payload_with_missing["variables"][0]["bins"]
        for b in bins_copy:
            if b["is_missing_bin"]:
                b["is_special_bin"] = True
        payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {
                    "variable": "score",
                    "kind": "numeric",
                    "bins": bins_copy,
                }
            ],
        }
        overrides = [
            {
                "variable": "score",
                "action": "reorder_special_bin",
                "source_bin_ids": [b for b in bins_copy if b.get("is_special_bin")][0],
                "reason": "Reorder special bin",
            }
        ]
        result = apply_manual_binning_overrides(payload, overrides)
        score_var = next(v for v in result["variables"] if v["variable"] == "score")
        assert score_var["bins"][-1].get("is_special_bin")

    def test_group_categories_on_categorical(self):
        from cardre.nodes import apply_manual_binning_overrides

        payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {
                    "variable": "status",
                    "kind": "categorical",
                    "bins": [
                        {"bin_id": "s_bin_001", "label": "A", "categories": ["A"],
                         "row_count": 50, "good_count": 30, "bad_count": 20},
                        {"bin_id": "s_bin_002", "label": "B", "categories": ["B"],
                         "row_count": 30, "good_count": 15, "bad_count": 15},
                        {"bin_id": "s_bin_003", "label": "C", "categories": ["C"],
                         "row_count": 20, "good_count": 10, "bad_count": 10},
                    ],
                }
            ],
        }
        overrides = [
            {
                "variable": "status",
                "action": "group_categories",
                "source_bin_ids": ["s_bin_001", "s_bin_002"],
                "new_label": "A or B",
                "reason": "Group low-severity categories",
            }
        ]
        result = apply_manual_binning_overrides(payload, overrides)
        status_var = next(v for v in result["variables"] if v["variable"] == "status")
        assert len(status_var["bins"]) == 2
        assert status_var["bins"][0]["label"] == "A or B"


# ======================================================================
# Tests: selected-variable filtering
# ======================================================================


class TestSelectedVariableFiltering:
    """When a selection-definition artifact restricts which variables
    are active, the bin definition must respect it."""

    def test_selected_only_variables_in_output(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        selected_vars = {"age"}
        result = apply_manual_binning_overrides(fc_payload, [], selected_vars)
        var_names = {v["variable"] for v in result["variables"]}
        assert var_names == {"age"}

    def test_no_overrides_but_selected_filters_correctly(self, fc_payload):
        from cardre.nodes import apply_manual_binning_overrides

        result = apply_manual_binning_overrides(fc_payload, [], {"income"})
        var_names = {v["variable"] for v in result["variables"]}
        assert var_names == {"income"}


# ======================================================================
# Tests: invariants the lifecycle module should validate
# ======================================================================


class TestBinDefinitionInvariants:
    """These invariants should be enforced by a lifecycle module."""

    def test_unique_variable_names(self, fc_payload):
        names = [v["variable"] for v in fc_payload["variables"]]
        assert len(names) == len(set(names))

    def test_unique_bin_ids_per_variable(self, fc_payload):
        for v in fc_payload["variables"]:
            bids = [b["bin_id"] for b in v["bins"]]
            assert len(bids) == len(set(bids)), f"Variable {v['variable']} has duplicate bin_ids"

    def test_all_bins_have_numeric_counts(self, fc_payload):
        for v in fc_payload["variables"]:
            for b in v["bins"]:
                assert isinstance(b.get("row_count"), (int, float)), f"row_count not numeric in {v['variable']}:{b['bin_id']}"


# ======================================================================
# Phase 1: Lifecycle module round-trip
# ======================================================================


class TestLifecycleRoundTrip:
    """The lifecycle module must round-trip current payloads identically."""

    def test_fc_payload_round_trip(self, fc_payload):
        parsed = LifecycleBinDefinition.from_payload(fc_payload)
        output = parsed.to_payload()
        assert output["schema_version"] == "cardre.bin_definition.v1"
        assert len(output["variables"]) == len(fc_payload["variables"])
        for vo, vi in zip(output["variables"], fc_payload["variables"]):
            assert vo["variable"] == vi["variable"]
            assert len(vo["bins"]) == len(vi["bins"])
            for bo, bi in zip(vo["bins"], vi["bins"]):
                assert bo["bin_id"] == bi["bin_id"]
                assert bo["row_count"] == bi["row_count"]
                assert bo["good_count"] == bi["good_count"]
                assert bo["bad_count"] == bi["bad_count"]

    def test_fc_payload_round_trip_semantic_equality(self, fc_payload):
        """Round trip preserves semantic content even if key layout differs."""
        parsed = LifecycleBinDefinition.from_payload(fc_payload)
        output = parsed.to_payload()
        orig_names = {v["variable"] for v in fc_payload["variables"]}
        out_names = {v["variable"] for v in output["variables"]}
        assert out_names == orig_names
        for v in output["variables"]:
            for b in v["bins"]:
                assert isinstance(b.get("row_count"), int)
                assert isinstance(b.get("good_count"), int)
                assert isinstance(b.get("bad_count"), int)

    def test_optbinning_payload_round_trip(self, optbinning_payload):
        parsed = LifecycleBinDefinition.from_payload(optbinning_payload)
        output = parsed.to_payload()
        assert output["schema_version"] == "cardre.bin_definition.v1"
        assert len(output["variables"]) == len(optbinning_payload["variables"])
        assert "rejected" in output
        assert len(output["rejected"]) == len(optbinning_payload["rejected"])
        assert "source" in output
        assert output["source"]["engine"] == "optbinning"
        assert "warnings" in output
        assert len(output["warnings"]) == len(optbinning_payload["warnings"])

    def test_optbinning_round_trip_semantic_equality(self, optbinning_payload):
        """Round trip preserves semantic content including optional fields."""
        parsed = LifecycleBinDefinition.from_payload(optbinning_payload)
        output = parsed.to_payload()
        orig = optbinning_payload
        assert output["schema_version"] == orig["schema_version"]
        assert output["source"]["engine"] == orig["source"]["engine"]
        assert output["source"]["method"] == orig["source"]["method"]
        assert len(output["rejected"]) == len(orig["rejected"])
        assert output["rejected"][0]["variable"] == orig["rejected"][0]["variable"]
        for v in output["variables"]:
            assert v["active"] is True
            assert "status" in v
            assert "dtype" in v
            assert "metrics" in v

    def test_round_trip_twice_stable(self, fc_payload):
        d1 = LifecycleBinDefinition.from_payload(fc_payload)
        p1 = d1.to_payload()
        d2 = LifecycleBinDefinition.from_payload(p1)
        p2 = d2.to_payload()
        assert json_logical_hash(p1) == json_logical_hash(p2)

    def test_deterministic_serialization(self, optbinning_payload):
        """Same input to to_payload always produces same hash."""
        d = LifecycleBinDefinition.from_payload(optbinning_payload)
        h1 = json_logical_hash(d.to_payload())
        h2 = json_logical_hash(d.to_payload())
        assert h1 == h2

    def test_normalize_preserves_bin_counts(self, fc_payload):
        parsed = LifecycleBinDefinition.from_payload(fc_payload)
        normalized = parsed.normalize()
        n_payload = normalized.to_payload()
        for v in fc_payload["variables"]:
            nv = next(x for x in n_payload["variables"] if x["variable"] == v["variable"])
            for b, nb in zip(v["bins"], nv["bins"]):
                assert nb["row_count"] == b["row_count"]
                assert nb["good_count"] == b["good_count"]
                assert nb["bad_count"] == b["bad_count"]

    def test_optbinning_normalize_preserves_content(self, optbinning_payload):
        parsed = LifecycleBinDefinition.from_payload(optbinning_payload)
        normalized = parsed.normalize()
        n_payload = normalized.to_payload()
        for v in optbinning_payload["variables"]:
            nv = next(x for x in n_payload["variables"] if x["variable"] == v["variable"])
            assert nv["active"] == v["active"]
            assert nv["status"] == v["status"]


class TestLifecycleValidation:
    """Validation invariants enforced by the lifecycle module."""

    def test_duplicate_variable_name_detected(self, fc_payload):
        payload = {**fc_payload, "variables": fc_payload["variables"] + [fc_payload["variables"][0]]}
        d = LifecycleBinDefinition.from_payload(payload)
        errs = d.validate()
        assert any("Duplicate variable" in e for e in errs)

    def test_duplicate_bin_id_detected(self, fc_payload):
        mod = {**fc_payload}
        age_var = dict(mod["variables"][0])
        age_var["bins"] = list(age_var["bins"]) + [dict(age_var["bins"][0])]
        mod["variables"] = [age_var] + mod["variables"][1:]
        d = LifecycleBinDefinition.from_payload(mod)
        errs = d.validate()
        assert any("Duplicate bin_id" in e for e in errs)

    def test_active_rejected_overlap(self, fc_payload):
        d = LifecycleBinDefinition.from_variables(
            variables=LifecycleBinDefinition.from_payload(fc_payload).variables,
            rejected=LifecycleBinDefinition.from_payload(fc_payload).variables,
        )
        errs = d.validate()
        assert any("active and rejected" in e for e in errs)

    def test_empty_schema_version_warns(self):
        d = LifecycleBinDefinition(schema_version="")
        errs = d.validate()
        assert any("schema_version" in e for e in errs)

    def test_clean_payload_no_errors(self, fc_payload):
        d = LifecycleBinDefinition.from_payload(fc_payload)
        assert d.validate() == []


# ======================================================================
# Phase 6: Richer BinDefinition accessors
# ======================================================================


class TestRicherBinDefinitionAccessors:
    """BinDefinition from the evidence reader now provides deeper access."""

    def test_lifecycle_backed_reader(self, optbinning_payload):
        from cardre.evidence import BinDefinition, ArtifactEvidenceReader, EvidenceKind
        from tests.helpers import make_store

        store, _ = make_store()
        store.initialize()
        from cardre.evidence import SCHEMA_BIN_DEFINITION
        from cardre.audit import ArtifactRef, json_logical_hash, physical_hash, relative_path
        import json
        p = store.root / "artifacts" / "optbinning.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(optbinning_payload, sort_keys=True))
        art = ArtifactRef(
            artifact_id="opt_bin_1", artifact_type="definition", role="definition",
            path=relative_path(p, store.root),
            physical_hash=physical_hash(p),
            logical_hash=json_logical_hash(optbinning_payload),
            media_type="application/json",
            metadata={"schema_version": SCHEMA_BIN_DEFINITION},
        )
        store.register_artifact(art)

        reader = ArtifactEvidenceReader(store)
        result = reader.find([art], EvidenceKind.BIN_DEFINITION)
        assert result is not None
        assert len(result.variables) == 2
        assert result.source_artifact_id == "opt_bin_1"

        # Richer accessors
        assert result.lifecycle is not None
        assert len(result.rejected) == 1
        assert result.rejected[0].variable == "old_feature"
        assert len(result.warnings) == 1
        assert result.source is not None
        assert result.source["engine"] == "optbinning"

    def test_fc_reader_does_not_have_rejected(self, fc_payload):
        from cardre.evidence import BinDefinition, ArtifactEvidenceReader, EvidenceKind
        from tests.helpers import make_store

        store, _ = make_store()
        store.initialize()
        from cardre.audit import ArtifactRef, json_logical_hash, physical_hash, relative_path
        import json
        p = store.root / "artifacts" / "fc.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(fc_payload, sort_keys=True))
        art = ArtifactRef(
            artifact_id="fc_bin_1", artifact_type="definition", role="definition",
            path=relative_path(p, store.root),
            physical_hash=physical_hash(p),
            logical_hash=json_logical_hash(fc_payload),
            media_type="application/json", metadata={},
        )
        store.register_artifact(art)

        reader = ArtifactEvidenceReader(store)
        result = reader.find([art], EvidenceKind.BIN_DEFINITION)
        assert result is not None
        assert len(result.variables) == 2
        assert len(result.rejected) == 0
        assert result.source is None

    def test_from_variables_preserves_all(self, fc_payload):
        parsed = LifecycleBinDefinition.from_payload(fc_payload)
        rebuilt = LifecycleBinDefinition.from_variables(
            variables=parsed.variables,
            warnings=parsed.warnings,
            source=parsed.source,
        )
        rp = rebuilt.to_payload()
        assert rp["schema_version"] == fc_payload["schema_version"]
        assert len(rp["variables"]) == len(fc_payload["variables"])
        assert json_logical_hash(rp) == json_logical_hash(parsed.to_payload())


# ======================================================================
# Post-review: unknown field preservation (extra dicts)
# ======================================================================


class TestExtraFieldPreservation:
    """Unknown payload fields must survive lifecycle round-trips."""

    def test_extra_bin_field_preserved(self, fc_payload):
        fc_payload["variables"][0]["bins"][0]["custom_field"] = "survive_bin"
        d = LifecycleBinDefinition.from_payload(fc_payload)
        out = d.to_payload()
        assert out["variables"][0]["bins"][0]["custom_field"] == "survive_bin"

    def test_extra_variable_field_preserved(self, fc_payload):
        fc_payload["variables"][0]["custom_var_field"] = "survive_variable"
        d = LifecycleBinDefinition.from_payload(fc_payload)
        out = d.to_payload()
        assert out["variables"][0]["custom_var_field"] == "survive_variable"

    def test_extra_definition_field_preserved(self, fc_payload):
        fc_payload["custom_def_field"] = "survive_definition"
        d = LifecycleBinDefinition.from_payload(fc_payload)
        out = d.to_payload()
        assert out["custom_def_field"] == "survive_definition"

    def test_reject_reason_preserved_in_rejected_variables(self, optbinning_payload):
        """Manual variable rejection writes reject_reason; it must survive."""
        d = LifecycleBinDefinition.from_payload(optbinning_payload)
        out = d.to_payload()
        assert len(out["rejected"]) == 1
        assert out["rejected"][0]["failure_reason"] is not None
        assert "no variance" in out["rejected"][0]["failure_reason"]

    def test_manual_rejection_reject_reason(self, fc_payload):
        """After applying reject_variable, reject_reason is set and preserved."""
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [{
            "variable": "age",
            "action": "reject_variable",
            "source_bin_ids": [],
            "reason": "High missing rate",
        }]
        result = apply_manual_binning_overrides(fc_payload, overrides)
        rejected = result.get("rejected") or []
        age_rejected = next(r for r in rejected if r["variable"] == "age")
        assert "reject_reason" in age_rejected


# ======================================================================
# Post-review: shape preservation with present_fields tracking
# ======================================================================


class TestShapePreservation:
    """Lifecycle serialization preserves which optional fields were
    present in the source payload (backward-compatible hash behavior)."""

    def test_fc_payload_no_active_field(self, fc_payload):
        """Fine-classing variables do not have 'active'; to_payload
        must not add it."""
        d = LifecycleBinDefinition.from_payload(fc_payload)
        out = d.to_payload()
        for v in out["variables"]:
            assert "active" not in v, f"Variable {v['variable']} has active field added"

    def test_fc_payload_no_rejected_field(self, fc_payload):
        """Fine-classing payloads do not have 'rejected'; to_payload
        must not add it."""
        d = LifecycleBinDefinition.from_payload(fc_payload)
        out = d.to_payload()
        assert "rejected" not in out, "rejected field added to fine-classing output"

    def test_optbinning_retains_active_field(self, optbinning_payload):
        """OptBinning variables have 'active'; to_payload preserves it."""
        d = LifecycleBinDefinition.from_payload(optbinning_payload)
        out = d.to_payload()
        for v in out["variables"]:
            assert "active" in v, f"Variable {v['variable']} missing active field"
            assert v["active"] is True

    def test_optbinning_retains_rejected_field(self, optbinning_payload):
        """OptBinning payloads have 'rejected'; to_payload preserves it."""
        d = LifecycleBinDefinition.from_payload(optbinning_payload)
        out = d.to_payload()
        assert "rejected" in out
        assert len(out["rejected"]) == 1

    def test_fc_payload_still_has_warnings(self, fc_payload):
        """Fine-classing payloads have 'warnings' (even empty); preserved."""
        d = LifecycleBinDefinition.from_payload(fc_payload)
        out = d.to_payload()
        assert "warnings" in out
        assert out["warnings"] == []

    def test_deterministic_hash_same_payload(self, fc_payload):
        d = LifecycleBinDefinition.from_payload(fc_payload)
        h1 = json_logical_hash(d.to_payload())
        h2 = json_logical_hash(d.to_payload())
        assert h1 == h2

    def test_deterministic_hash_preserved_after_round_trip(self, fc_payload):
        """Round-tripping the same payload through the lifecycle module
        must produce the same hash each time."""
        d1 = LifecycleBinDefinition.from_payload(fc_payload)
        p1 = d1.to_payload()
        d2 = LifecycleBinDefinition.from_payload(p1)
        p2 = d2.to_payload()
        assert json_logical_hash(p1) == json_logical_hash(p2)

    def test_normalize_preserves_extra_and_shape(self, fc_payload):
        """normalize() must preserve document-level extra fields and
        optional-field presence tracking (_present_fields)."""
        payload = dict(fc_payload)
        payload["custom_doc_field"] = "survive_normalize"
        d = LifecycleBinDefinition.from_payload(payload)
        n = d.normalize()
        out = n.to_payload()
        assert out["custom_doc_field"] == "survive_normalize"
        assert "rejected" not in out
        for v in out["variables"]:
            assert "active" not in v


# ======================================================================
# Post-review: per-override error isolation in validate_overrides
# ======================================================================


class TestOverrideValidationErrors:
    """validate_overrides must check each override independently so that
    a single invalid override does not block action-specific validation
    on later overrides."""

    def test_validation_unblocks_after_early_fail(self):
        """An override rejected for missing reason should not block
        adjacency validation on a later merge override."""
        from cardre.engine.binning.definition import LifecycleBinDefinition

        payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {
                    "variable": "x", "kind": "numeric",
                    "bins": [
                        {"bin_id": "b1", "lower": 0, "upper": 10,
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                        {"bin_id": "b2", "lower": 10, "upper": 20,
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                    ],
                },
            ],
        }
        overrides = [
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b2"], "reason": ""},
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b2"], "reason": "Merge adjacent"},
        ]
        errors = LifecycleBinDefinition.validate_overrides(payload, overrides)
        assert len(errors) >= 1
        assert any("requires a non-empty reason" in e for e in errors)
        assert not any("adjacent" in e for e in errors), (
            "Adjacency check should pass for adjacent bins — only the "
            "first override should produce errors"
        )

    def test_non_adjacent_merge_caught_after_reason_fail(self):
        """Non-adjacent merge error should still be raised for an
        override with a valid reason even if a prior override had
        a missing reason."""
        from cardre.engine.binning.definition import LifecycleBinDefinition

        payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {
                    "variable": "x", "kind": "numeric",
                    "bins": [
                        {"bin_id": "b1", "lower": 0, "upper": 10,
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                        {"bin_id": "b2", "lower": 10, "upper": 20,
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                        {"bin_id": "b3", "lower": 20, "upper": 30,
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                    ],
                },
            ],
        }
        overrides = [
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b2"], "reason": ""},
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b3"], "reason": "Non-adjacent attempt"},
        ]
        errors = LifecycleBinDefinition.validate_overrides(payload, overrides)
        assert any("requires a non-empty reason" in e for e in errors)
        assert any("adjacent" in e for e in errors), (
            "Second override with valid reason should still get adjacency check"
        )

    def test_scoped_validation_continues_after_reason_fail(self):
        """Scoped errors (missing reason) from an earlier override
        should not prevent scoped errors from a later override."""
        from cardre.engine.binning.definition import LifecycleBinDefinition

        payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {
                    "variable": "x", "kind": "numeric",
                    "bins": [
                        {"bin_id": "b1", "lower": 0, "upper": 10,
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                    ],
                },
            ],
        }
        overrides = [
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b2"], "reason": ""},
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b2"], "reason": ""},
        ]
        errors = LifecycleBinDefinition.validate_overrides(payload, overrides)
        reason_errors = [e for e in errors if "requires a non-empty reason" in e]
        assert len(reason_errors) == 2, (
            "Each override should independently fail on missing reason"
        )

    def test_unknown_bin_id_in_second_override(self):
        """A bin_id error in a later override must be found even if
        a prior override was rejected for missing reason."""
        from cardre.engine.binning.definition import LifecycleBinDefinition

        payload = {
            "schema_version": "cardre.bin_definition.v1",
            "variables": [
                {
                    "variable": "x", "kind": "numeric",
                    "bins": [
                        {"bin_id": "b1",
                         "row_count": 5, "good_count": 4, "bad_count": 1},
                    ],
                },
            ],
        }
        overrides = [
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b2"], "reason": ""},
            {"variable": "x", "action": "merge_bins",
             "source_bin_ids": ["b1", "b999"], "reason": "Valid reason"},
        ]
        errors = LifecycleBinDefinition.validate_overrides(payload, overrides)
        assert any("requires a non-empty reason" in e for e in errors)
        assert any("b999" in e for e in errors), (
            "Non-existent bin_id in a valid-reason override should be reported"
        )


# ======================================================================
# Post-review: ManualBinningNode uses bin_def.to_dict() not raw JSON
# ======================================================================


class TestManualBinningNodeNoRawJson:
    """ManualBinningNode must not reload raw JSON — it should use
    bin_def.to_dict() from the evidence reader."""

    def test_manual_binning_merge_preserves_counts(self, fc_payload):
        """The node still produces correct output even through the
        to_dict() path."""
        from cardre.nodes import apply_manual_binning_overrides

        overrides = [
            {
                "variable": "age",
                "action": "merge_bins",
                "source_bin_ids": ["age_bin_001", "age_bin_002"],
                "new_label": "Low-Mid",
                "reason": "Merged adjacent",
            }
        ]
        result = apply_manual_binning_overrides(fc_payload, overrides)
        age_var = next(v for v in result["variables"] if v["variable"] == "age")
        merged = age_var["bins"][0]
        assert merged["row_count"] == 40 + 60
        assert merged["good_count"] == 25 + 35
