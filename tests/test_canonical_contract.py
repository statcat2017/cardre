"""Canonical contract tests — enforce the canonical architecture.

These tests guard against regression to legacy node identities, aliases,
and compatibility mechanisms that have been removed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cardre.nodes.registry import NodeRegistry
from cardre.workflows.scorecard import build_canonical_scorecard_steps


def test_only_one_automatic_binning_node_registered():
    reg = NodeRegistry.with_defaults()
    assert reg.has("cardre.automatic_binning")
    assert not reg.has("cardre.fine_classing")
    assert not reg.has("cardre.auto_binning_fit")
    assert not reg.has("cardre.binning")


def test_manual_binning_distinct_node():
    reg = NodeRegistry.with_defaults()
    manual = reg.resolve("cardre.manual_binning")
    assert manual.category == "refinement"
    assert manual.node_type == "cardre.manual_binning"


def test_canonical_automatic_binning_has_explicit_method():
    steps = build_canonical_scorecard_steps("dummy.csv")
    auto_step = next(s for s in steps if s.step_id == "automatic-binning")
    assert "method" in auto_step.params, (
        "automatic-binning step must have an explicit method param"
    )
    assert auto_step.params["method"] == "fine_classing"
    assert auto_step.params_hash, "params_hash must be non-empty"
    from cardre.domain.artifacts import json_logical_hash
    expected_hash = json_logical_hash(auto_step.params)
    assert auto_step.params_hash == expected_hash, (
        "params_hash must be based on the explicit params"
    )


def test_no_compat_evidence_aliases_in_source():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "cardre"
    banned_names = {
        "WOE_APPLICATION_EVIDENCE", "SCORE_APPLICATION_EVIDENCE",
        "SCHEMA_WOE_APPLICATION_EVIDENCE", "SCHEMA_SCORE_APPLICATION_EVIDENCE",
        "LegacyEvidenceCompatibilityError", "SCHEMA_RUN_MANIFEST",
        "RUN_MANIFEST", "RunManifestEvidence",
    }
    banned_dotted = {"EvidenceKind.RUN_MANIFEST"}
    for py in sorted(root.rglob("*.py")):
        if ".venv" in str(py) or "__pycache__" in str(py):
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                for alias in node.names:
                    if alias.name in banned_names:
                        raise AssertionError(
                            f"{py.relative_to(root)} imports banned identifier {alias.name!r}"
                        )
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in banned_names:
                        raise AssertionError(
                            f"{py.relative_to(root)} defines banned identifier {target.id!r}"
                        )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in banned_names:
                    raise AssertionError(
                        f"{py.relative_to(root)} defines banned identifier {node.target.id!r}"
                    )
            elif isinstance(node, ast.ClassDef) and node.name in banned_names:
                raise AssertionError(
                    f"{py.relative_to(root)} defines banned class {node.name!r}"
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in banned_names:
                raise AssertionError(
                    f"{py.relative_to(root)} defines banned function {node.name!r}"
                )
            elif isinstance(node, ast.Name) and node.id in banned_names:
                raise AssertionError(
                    f"{py.relative_to(root)} uses banned identifier {node.id!r}"
                )
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                full = f"{node.value.id}.{node.attr}"
                if full in banned_dotted:
                    raise AssertionError(
                        f"{py.relative_to(root)} uses banned identifier {full!r}"
                    )


def test_score_scaling_defaults_match_reader_and_report_model():
    from cardre._evidence.models.model import ScoreScaling
    from cardre.reporting.schema import ScoreScalingInfo

    assert ScoreScaling().score_direction == "higher_is_lower_risk"
    assert ScoreScalingInfo().score_direction == "higher_is_lower_risk"


def test_score_scaling_reads_points_to_double_odds():
    from cardre._evidence.models.model import ScoreScaling
    s = ScoreScaling.from_json({"points_to_double_odds": 40, "base_score": 600})
    assert s.points_to_double_odds == 40


def test_score_scaling_ignores_pdo_key():
    from cardre._evidence.models.model import ScoreScaling
    s = ScoreScaling.from_json({"pdo": 40, "base_score": 600})
    assert s.points_to_double_odds == 20  # default — pdo was ignored


def test_score_scaling_reads_score_direction():
    from cardre._evidence.models.model import ScoreScaling
    s = ScoreScaling.from_json({"score_direction": "higher_is_better", "base_score": 600})
    assert s.score_direction == "higher_is_better"
    assert s.higher_score_is_lower_risk is False


def test_model_artifact_rejects_list_coefficients():
    from cardre.modeling.schema import ModelArtifactV1

    with pytest.raises(ValueError, match=r"dict \{variable: coefficient\}"):
        ModelArtifactV1.from_dict(
            {
                "schema_version": "cardre.model_artifact.v1",
                "model_family": "logistic_regression",
                "target_column": "bad_flag",
                "target_event_value": "bad",
                "class_mapping": {"0": "good", "1": "bad"},
                "feature_contract": {"features": ["age_woe"]},
                "model_payload": {
                    "intercept": -0.4,
                    "coefficients": [
                        {"variable_name": "age_woe", "coefficient": 0.8},
                    ],
                },
            }
        )


def test_validation_metrics_rejects_legacy_metrics_key():
    from cardre._evidence.models.validation import ValidationMetrics

    with pytest.raises(ValueError, match="canonical 'roles'"):
        ValidationMetrics.from_json({"metrics": {"train": {"auc": 0.75}}})


def test_cutoff_analysis_rejects_legacy_score_key():
    from cardre._evidence.models.validation import CutoffAnalysis

    with pytest.raises(ValueError, match="score_cutoff"):
        CutoffAnalysis.from_json({"cutoff_tables": {"train": [{"score": 100}]}})


def test_model_artifact_requires_schema_version():
    from cardre.modeling.schema import ModelArtifactV1
    payload = {
        "model_family": "logistic_regression",
        "target_column": "y",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["x"]},
        "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
        "training": {"row_count": 100},
    }
    with pytest.raises(ValueError, match="requires schema_version"):
        ModelArtifactV1.from_dict(payload)


def test_model_artifact_rejects_wrong_schema_version():
    from cardre.modeling.schema import ModelArtifactV1
    payload = {
        "schema_version": "cardre.model_artifact.v2",
        "model_family": "logistic_regression",
        "target_column": "y",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {"features": ["x"]},
        "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
        "training": {"row_count": 100},
    }
    with pytest.raises(ValueError, match="requires schema_version"):
        ModelArtifactV1.from_dict(payload)


# ---------------------------------------------------------------------------
# Forbidden imports — migration guard
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parent.parent

BANNED_IDENTIFIERS = {
    "ProjectStore",
    "CardreConfig",
    "ArtifactEvidenceReader",
}

BANNED_IMPORTS = {
    "sqlite3",
    "os.environ",
    "os.getenv",
}

BANNED_ATTRIBUTES = {
    "context.store",
    "store.root",
}

ALLOWED_PREFIXES = {
    "cardre.adapters.sqlite": {"sqlite3"},
    "cardre.bootstrap.settings": {"os.environ", "os.getenv"},
    "cardre.adapters.evidence": {"ArtifactEvidenceReader"},
}


def _is_allowed(filepath: str, symbol: str) -> bool:
    for prefix, allowed in ALLOWED_PREFIXES.items():
        if filepath.startswith(prefix) and symbol in allowed:
            return True
    return False


@pytest.mark.xfail(
    strict=False,
    reason="Migration in progress; enforced after Batch 07",
)
def test_forbidden_imports_outside_adapters() -> None:
    """AST-walk cardre/ and ban forbidden identifiers outside allowed packages."""
    cardre_dir = REPO_ROOT / "cardre"
    violations: list[str] = []

    for pyfile in sorted(cardre_dir.rglob("*.py")):
        rel = pyfile.relative_to(REPO_ROOT)
        rel_str = str(rel)
        try:
            tree = ast.parse(pyfile.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in BANNED_IMPORTS and not _is_allowed(rel_str, alias.name):
                        violations.append(f"{rel_str}:{node.lineno}: import {alias.name}")

            if isinstance(node, ast.ImportFrom):
                if node.module in BANNED_IMPORTS and not _is_allowed(rel_str, node.module):
                    violations.append(f"{rel_str}:{node.lineno}: from {node.module} import ...")
                if node.module and node.module.startswith("cardre.store"):
                    violations.append(f"{rel_str}:{node.lineno}: from {node.module} import ... (store)")
                if node.module and node.module.startswith("cardre.config"):
                    violations.append(f"{rel_str}:{node.lineno}: from {node.module} import ... (config)")

            if isinstance(node, ast.Name):
                if node.id in BANNED_IDENTIFIERS and not _is_allowed(rel_str, node.id):
                    violations.append(f"{rel_str}:{node.lineno}: reference to {node.id}")

            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    full = f"{node.value.id}.{node.attr}"
                    if full in BANNED_ATTRIBUTES:
                        violations.append(f"{rel_str}:{node.lineno}: {full}")

    if violations:
        pytest.fail(
            "Forbidden imports/symbols found (xfail during migration):\n"
            + "\n".join(violations)
        )
