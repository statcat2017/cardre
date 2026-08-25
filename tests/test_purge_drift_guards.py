"""Repository drift guards for the one-product purge.

These guards enforce the final one-cardre architecture on production
implementation paths. They scan ``cardre/`` (not tests, not historical ADRs or
plans, and not docstring/comment text) so that historical records and fixtures
that intentionally document rejected behavior do not produce false positives.

The guards cover:

1. No launch-mode, deferred-tier, ``coming_soon``, or alternate model-family
   dispatch surface in production code.
2. Production packages contain no test-fake node implementations.
3. Strict persisted parsers reject unknown fields and missing current fields.
4. The import boundary accepts only Parquet.
5. SCORE_TABLE has exactly one tabular publication path and is not published
   as JSON anywhere in the production tree.
6. No governance branch scope or compatibility fallback remains.
7. Removed scorecard-methodology branches (alternate binning/penalised logit
   methods, non-threshold clustering methods) do not resurface as real code.
8. Strict WOE transformation has no permissive missing-policy fallback.
9. Artifact lookup has no ``physical_hash`` compatibility fallback.

The registry==canonical invariant is enforced separately in
``tests/test_registry_canonical_invariant.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cardre.bootstrap.node_catalogue import build_default_catalogue

REPO_ROOT = Path(__file__).resolve().parent.parent
CARRE_SRC = REPO_ROOT / "cardre"


def _production_py_files() -> list[Path]:
    """All production ``cardre/*.py`` files, excluding caches."""
    return sorted(
        py
        for py in CARRE_SRC.rglob("*.py")
        if "__pycache__" not in py.parts
    )


def _source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Tokens that indicate removed deferred/launch/alternate-family surface, and
# removed scorecard-methodology branches. Scanned as AST nodes, including
# string literals; comments are excluded because they are not in the AST.
BANNED_IDENTIFIERS: frozenset[str] = frozenset({
    "launch_mode",
    "CARDRE_LAUNCH_MODE",
    "NodeTier",
    "coming_soon",
    "NoopNode",
    "DummyFitNode",
    "_SKLEARN_FAMILIES",
    "_ENSEMBLE_FAMILIES",
    "CARDRE_GOVERNANCE",
    "GovernanceNotEnabled",
    "BRANCH_TABLES_SQL",
    # Removed scorecard methodology — binning / penalised logit / clustering
    "optbinning",
    "OptBinning",
    "penalised_logit",
    "elasticnet",
    "MissingWoePolicy",
    "VALID_PENALTIES",
    "VALID_SOLVERS",
    "hierarchical",
    "varclus_pca",
    "mixed_type",
    "target_aware",
})


def _banned_usages(tree: ast.Module) -> list[str]:
    """Return banned identifier usages found as real code."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BANNED_IDENTIFIERS:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_IDENTIFIERS:
            found.append(node.attr)
        elif isinstance(node, ast.ClassDef) and node.name in BANNED_IDENTIFIERS:
            found.append(node.name)
        elif isinstance(node, ast.keyword) and node.arg in BANNED_IDENTIFIERS:
            found.append(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.extend(value for value in BANNED_IDENTIFIERS if value in node.value)
    return found


def test_banned_usage_detector_catches_reintroduction_forms():
    """The detector must catch names, attributes, literals, classes, and kwargs."""
    tree = ast.parse(
        """
class NoopNode: pass
value = obj.launch_mode
flag = \"CARDRE_GOVERNANCE\"
call(coming_soon=True)
"""
    )
    assert set(_banned_usages(tree)) >= {
        "NoopNode", "launch_mode", "CARDRE_GOVERNANCE", "coming_soon",
    }


def test_production_has_no_deferred_or_launch_surface():
    """No launch/deferred tier, coming-soon, or alternate-family dispatch
    tokens may appear as real code in production packages."""
    violations: list[tuple[str, int, str]] = []
    for py in _production_py_files():
        tree = ast.parse(_source_text(py))
        for name in _banned_usages(tree):
            violations.append((py.relative_to(REPO_ROOT).as_posix(), name))

    assert not violations, (
        "Production code must not contain deferred/launch/alternate-family "
        "surface:\n" + "\n".join(f"{p}: {n}" for p, n in violations)
    )


def test_registered_nodes_are_real_implementations():
    """Every registered production node class must be a concrete ``NodeType``
    declared in the production package (not a test fake)."""
    cat = build_default_catalogue()
    for node_type in cat.list_types():
        cls = cat.resolve(node_type)
        assert cls.__module__.startswith("cardre."), (
            f"registered node {node_type!r} is implemented in {cls.__module__!r}, "
            "outside the production cardre package"
        )
        assert "__definition__" in cls.__dict__, (
            f"registered node {node_type!r} ({cls.__module__}) has no explicit "
            "NodeDefinition and is not a production implementation"
        )


def test_strict_model_parser_rejects_unknown_and_missing_fields():
    """The persisted model parser must reject unknown top-level fields and
    require every current field (no reconstruction of omitted fields)."""
    from cardre.modeling.schema import ModelArtifactV1

    payload = {
        "schema_version": "cardre.model_artifact.v1",
        "target_column": "y",
        "target_event_value": "bad",
        "class_mapping": {"good": "good", "bad": "bad"},
        "probability_column_index": 1,
        "feature_contract": {
            "features": ["x"],
            "transformation_strategy": "woe",
            "order_hash": "h",
            "missing_policy": "error",
            "unknown_category_policy": "error",
        },
        "model_payload": {"intercept": 0.0, "coefficients": {"x": 1.0}},
        "training": {"row_count": 100},
        "source_variables": ["x_src"],
        "bad_class_label": "bad",
        "warnings": [],
    }

    unknown = dict(payload)
    unknown["model_family"] = "random_forest"
    with pytest.raises(ValueError, match="unknown key"):
        ModelArtifactV1.from_dict(unknown)

    missing = dict(payload)
    del missing["training"]
    with pytest.raises(ValueError, match="requires the following key"):
        ModelArtifactV1.from_dict(missing)


def test_import_boundary_accepts_only_parquet():
    """The import node must read Parquet only. No CSV/TSV/delimiter/encoding
    reading may appear in the import node."""
    banned_import_apis = {
        "read_csv",
        "read_delim",
        "read_table",
        "read_fwf",
        "read_excel",
        "read_ndjson",
        "read_json",
    }
    import_node = CARRE_SRC / "nodes" / "prep" / "import_.py"
    text = _source_text(import_node)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in banned_import_apis:
                pytest.fail(
                    f"import_.py uses banned data-reader {attr!r}; the import "
                    "boundary accepts Parquet only"
                )
    assert "read_parquet" in text, "import_.py must read via pl.read_parquet"


def test_score_table_has_single_tabular_publication():
    """SCORE_TABLE must be published exactly once, as a Parquet table. No
    duplicate JSON publication of the scorecard table may remain anywhere in
    the production tree."""
    publish_table_calls = []
    publish_json_calls = []
    for path in _production_py_files():
        tree = ast.parse(_source_text(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            kind = next((kw.value for kw in node.keywords if kw.arg == "kind"), None)
            if not (
                isinstance(kind, ast.Attribute)
                and isinstance(kind.value, ast.Name)
                and kind.value.id == "EvidenceKind"
                and kind.attr == "SCORE_TABLE"
            ):
                continue
            if node.func.attr == "publish_table":
                publish_table_calls.append(path)
            elif node.func.attr == "publish_json":
                publish_json_calls.append(path)
    assert len(publish_table_calls) == 1, (
        f"Production must publish the scorecard table exactly "
        f"once, got {len(publish_table_calls)} publish_table call(s)"
    )
    assert not publish_json_calls, (
        f"SCORE_TABLE must not be published as JSON: {publish_json_calls}"
    )


def test_score_table_publish_kind_is_evidence_kind_attribute():
    """The SCORE_TABLE publication kind must be the canonical
    ``EvidenceKind.SCORE_TABLE`` attribute (not a string literal or alias),
    so the whole-tree guard cannot be bypassed by a renamed reference."""
    scorecard_export = CARRE_SRC / "nodes" / "build" / "scoring_export.py"
    text = _source_text(scorecard_export)
    tree = ast.parse(text)
    kinds_seen: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        kind = next((kw.value for kw in node.keywords if kw.arg == "kind"), None)
        if (
            isinstance(kind, ast.Attribute)
            and isinstance(kind.value, ast.Name)
            and kind.value.id == "EvidenceKind"
            and kind.attr == "SCORE_TABLE"
        ):
            kinds_seen.append(node.func.attr)
    assert kinds_seen == ["publish_table"], (
        f"SCORE_TABLE must be published via EvidenceKind.SCORE_TABLE only, "
        f"got {kinds_seen}"
    )


def test_strict_woe_has_no_missing_policy_fallback():
    """WOE application must be strict: no permissive missing-policy fallback
    may remain on ``apply_woe_columns`` or its callers."""
    woe_path = CARRE_SRC / "domain" / "binning" / "woe.py"
    text = _source_text(woe_path)
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != "apply_woe_columns":
                continue
            arg_names = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
            assert "policy" not in arg_names, (
                "apply_woe_columns must not accept a permissive missing-policy parameter"
            )
    assert "MissingWoePolicy" not in text, (
        "MissingWoePolicy enum must not resurface; WOE application is strict"
    )


def test_methodology_branch_detector_catches_reintroduction_forms():
    """The detector must catch removed-methodology tokens as names, attributes,
    literals, classes, and kwargs."""
    tree = ast.parse(
        """
class OptBinning: pass
value = obj.penalised_logit
flag = \"MissingWoePolicy\"
call(target_aware=True)
method = varclus_pca
"""
    )
    found = set(_banned_usages(tree))
    assert found >= {"OptBinning", "penalised_logit", "MissingWoePolicy", "target_aware", "varclus_pca"}


def test_run_scope_is_closed_to_full_plan_only():
    """RunScope must contain only full_plan; no branch scope may remain."""
    from cardre.domain.run import RunScope

    assert [s.value for s in RunScope] == ["full_plan"], (
        f"RunScope must contain only full_plan, got {[s.value for s in RunScope]}"
    )


def test_schema_rejects_branch_run_scope():
    """The runs table CHECK constraint must not admit a 'branch' scope."""
    schema = CARRE_SRC / "adapters" / "sqlite" / "schema.py"
    text = _source_text(schema)
    for line in text.splitlines():
        if "run_scope" in line and "CHECK" in line:
            assert "'branch'" not in line, (
                f"schema.py run_scope CHECK constraint admits a branch scope: {line}"
            )


def test_artifact_lookup_has_no_compatibility_fallback():
    """Artifact lookup must use the current identifier only."""
    violations: list[str] = []
    for path in _production_py_files():
        tree = ast.parse(_source_text(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                if node.name == "artifact_ref" and any(
                    arg.arg == "physical_hash" for arg in args
                ):
                    violations.append(f"{path}: artifact_ref accepts physical_hash")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "artifact_ref" and any(
                    keyword.arg == "physical_hash" for keyword in node.keywords
                ):
                    violations.append(f"{path}: artifact_ref uses physical_hash")
    assert not violations, "Compatibility artifact lookup remains:\n" + "\n".join(violations)
