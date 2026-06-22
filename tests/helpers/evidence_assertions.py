"""Assertion helpers for typed evidence objects in tests."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def _payload(evidence: Any) -> dict[str, Any]:
    if isinstance(evidence, dict):
        return dict(evidence)
    if hasattr(evidence, "model_dump"):
        try:
            return evidence.model_dump(mode="json")
        except TypeError:
            return evidence.model_dump()
    if hasattr(evidence, "to_dict"):
        return evidence.to_dict()
    if is_dataclass(evidence):
        return asdict(evidence)
    raise AssertionError(f"Unsupported evidence object: {type(evidence)!r}")


def _source_artifact_id(evidence: Any, payload: dict[str, Any]) -> str:
    source = getattr(evidence, "source_artifact_id", payload.get("source_artifact_id", ""))
    if not source:
        raise AssertionError("source_artifact_id is missing")
    return str(source)


def _assert_fields(label: str, payload: dict[str, Any], expected: dict[str, Any]) -> None:
    for key, expected_value in expected.items():
        lookup_key = "pdo" if key == "points_to_double_odds" else key
        actual = payload.get(lookup_key)
        if actual != expected_value:
            raise AssertionError(f"{label}.{lookup_key}: expected {expected_value!r}, got {actual!r}")


def _variable_names(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key, []) or []
    names: list[str] = []
    for item in values:
        if isinstance(item, dict):
            name = item.get("variable_name", item.get("variable", ""))
            if name:
                names.append(str(name))
        else:
            name = getattr(item, "variable_name", getattr(item, "variable", ""))
            if name:
                names.append(str(name))
    return names


def assert_model_artifact(evidence, expected_kind="logistic_regression", **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    model_family = payload.get("model_family", payload.get("model_type", ""))
    if expected_kind and model_family != expected_kind:
        raise AssertionError(f"model_family: expected {expected_kind!r}, got {model_family!r}")
    _assert_fields("model", payload, fields)


def assert_bin_definition(evidence, expected_variables=None, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    if expected_variables is not None:
        actual = _variable_names(payload, "variables")
        if actual != list(expected_variables):
            raise AssertionError(f"bin_definition.variables: expected {list(expected_variables)!r}, got {actual!r}")
    _assert_fields("bin_definition", payload, fields)


def assert_selection_definition(evidence, expected_selected=None, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    if expected_selected is not None:
        actual = _variable_names(payload, "selected")
        if actual != list(expected_selected):
            raise AssertionError(f"selection_definition.selected: expected {list(expected_selected)!r}, got {actual!r}")
    _assert_fields("selection_definition", payload, fields)


def assert_woe_iv_evidence(evidence, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    _assert_fields("woe_iv_evidence", payload, fields)


def assert_score_scaling(evidence, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    _assert_fields("score_scaling", payload, fields)


def assert_scorecard_bundle(evidence, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    _assert_fields("scorecard_bundle", payload, fields)


def assert_validation_evidence(evidence, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    _assert_fields("validation_evidence", payload, fields)


def assert_report_bundle(evidence, **fields):
    payload = _payload(evidence)
    _source_artifact_id(evidence, payload)
    _assert_fields("report_bundle", payload, fields)
