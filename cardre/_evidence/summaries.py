"""Per-kind evidence summarisers for the Cardre project.

Each summariser receives the raw artifact row dict and the already-parsed
typed evidence object.  Return values are plain dicts with kind-specific
keys plus an (unused) list-of-strings slot for future diagnostics.
"""

from __future__ import annotations

import json
from typing import Any


# ------------------------------------------------------------------
# Dispatch-key resolution
# ------------------------------------------------------------------

_SCHEMA_TO_KIND: dict[str, str] = {
    "cardre.modelling_metadata.v1": "target-definition",
    "cardre.profile_summary.v1": "profile",
    "cardre.split_summary.v1": "split",
    "cardre.bin_definition.v1": "binning",
    "cardre.woe_iv_evidence.v1": "woe-iv",
    "cardre.model_artifact.v1": "logistic-model",
    "cardre.ensemble_model_artifact.v1": "logistic-model",
    "cardre.score_scaling.v1": "score-scaling",
    "cardre.validation_metrics.v1": "validation-metrics",
    "cardre.validation_evidence.v1": "validation-metrics",
    "cardre.report_bundle.v1": "report-bundle",
}


def _resolve_kind(artifact_row: dict) -> str:
    """Return the dispatch key from artifact_row.

    Priority:
    1. ``evidence_kind`` in metadata / row
    2. ``schema_version`` mapped via ``_SCHEMA_TO_KIND``
    3. ``artifact_type``
    """
    metadata_raw: Any = artifact_row.get("metadata_json") or artifact_row.get("metadata", "{}")
    metadata: dict[str, Any]
    if isinstance(metadata_raw, str):
        try:
            metadata = json.loads(metadata_raw)
        except (json.JSONDecodeError, TypeError):
            metadata = {}
    elif isinstance(metadata_raw, dict):
        metadata = metadata_raw
    else:
        metadata = {}

    kind: str = metadata.get("evidence_kind", "") or artifact_row.get("evidence_kind", "")
    if kind:
        return kind

    schema_version: str = metadata.get("schema_version", "")
    mapped = _SCHEMA_TO_KIND.get(schema_version)
    if mapped:
        return mapped

    return artifact_row.get("artifact_type", "")


# ------------------------------------------------------------------
# Per-kind summarisers
# ------------------------------------------------------------------

def _summarise_profile(artifact_row: dict, payload: Any) -> dict:
    return {
        "row_count": getattr(payload, "row_count", 0),
        "column_count": getattr(payload, "column_count", 0),
        "dataset_role": artifact_row.get("role", ""),
    }


def _summarise_target_definition(artifact_row: dict, payload: Any) -> dict:
    good_values = getattr(payload, "good_values", None) or []
    bad_values = getattr(payload, "bad_values", None) or []
    good_label = str(good_values[0]) if good_values else ""
    bad_label = str(bad_values[0]) if bad_values else ""
    extra = getattr(payload, "extra", None) or {}
    return {
        "target_column": getattr(payload, "target_column", ""),
        "good_label": good_label,
        "bad_label": bad_label,
        "event_rate": extra.get("event_rate"),
    }


def _summarise_split(artifact_row: dict, payload: Any) -> dict:
    row_counts = getattr(payload, "row_counts", None) or {}
    return {
        "train_count": row_counts.get("train", 0),
        "test_count": row_counts.get("test", 0),
        "oot_count": row_counts.get("oot", 0),
    }


def _summarise_binning(artifact_row: dict, payload: Any) -> dict:
    variables = getattr(payload, "variables", None) or []
    variable_count = len(variables)
    bin_total = sum(len(getattr(v, "bins", None) or []) for v in variables)
    lifecycle = getattr(payload, "_lifecycle", None)
    if lifecycle is not None:
        missing_handling = getattr(lifecycle, "missing_handling", "as_is")
        special_handling = getattr(lifecycle, "special_handling", "as_is")
    else:
        missing_handling = "as_is"
        special_handling = "as_is"
    return {
        "variable_count": variable_count,
        "bin_total": bin_total,
        "missing_handling": missing_handling,
        "special_handling": special_handling,
    }


def _summarise_woe_iv(artifact_row: dict, payload: Any) -> dict:
    variables = getattr(payload, "variables", None) or []
    included = [v for v in variables if getattr(v, "status", "included") == "included"]
    ivals = sorted((getattr(v, "iv", 0.0) or 0.0) for v in included)
    top = sorted(included, key=lambda v: getattr(v, "iv", 0.0) or 0.0, reverse=True)[:3]
    return {
        "selected_variable_count": len(included),
        "iv_min": float(ivals[0]) if ivals else 0.0,
        "iv_max": float(ivals[-1]) if ivals else 0.0,
        "top_variables": [
            {"name": getattr(v, "variable_name", ""), "iv": float(getattr(v, "iv", 0.0) or 0.0)}
            for v in top
        ],
    }


def _summarise_logistic_model(artifact_row: dict, payload: Any) -> dict:
    training = getattr(payload, "training", None) or {}
    return {
        "variable_count": len(getattr(payload, "features", None) or []),
        "coefficient_count": len(getattr(payload, "coefficients", None) or []),
        "fit_status": training.get("status", "unknown"),
    }


def _summarise_score_scaling(artifact_row: dict, payload: Any) -> dict:
    return {
        "score_min": getattr(payload, "min_score", 0),
        "score_max": getattr(payload, "max_score", 0),
        "pdo": getattr(payload, "pdo", 20),
        "base_odds": str(getattr(payload, "base_odds", "50:1")),
        "base_score": getattr(payload, "base_score", 600),
    }


def _summarise_validation_metrics(artifact_row: dict, payload: Any) -> dict:
    result: dict[str, Any] = {}
    metrics_by_role = getattr(payload, "metrics_by_role", None) or {}
    for role_name in ("train", "test", "oot"):
        rm = metrics_by_role.get(role_name)
        if rm is not None:
            for key in ("gini", "ks", "auc"):
                val = getattr(rm, key, None)
                if val is not None:
                    result[key] = float(val)
            break
    psi = getattr(payload, "psi", None) or {}
    if psi:
        result["psi"] = {str(k): float(v) for k, v in psi.items() if isinstance(v, (int, float))}
    raw = getattr(payload, "_raw", None) or {}
    cal = raw.get("calibration_status") or (raw.get("calibration") or {}).get("status")
    if cal is not None:
        result["calibration_status"] = str(cal)
    return result


def _summarise_report_bundle(artifact_row: dict, payload: Any) -> dict:
    summary = getattr(payload, "summary", None) or {}
    return {
        "ready": bool(summary.get("ready", False)),
        "blocker_count": len(summary.get("blockers", [])),
        "warning_count": len(summary.get("warnings", [])),
    }


# ------------------------------------------------------------------
# Dispatch registry
# ------------------------------------------------------------------

_SUMMARISERS: dict[str, Any] = {
    "profile": _summarise_profile,
    "import": _summarise_profile,
    "target-definition": _summarise_target_definition,
    "split": _summarise_split,
    "binning": _summarise_binning,
    "woe-iv": _summarise_woe_iv,
    "logistic-model": _summarise_logistic_model,
    "score-scaling": _summarise_score_scaling,
    "validation-metrics": _summarise_validation_metrics,
    "report-bundle": _summarise_report_bundle,
}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def summarise(artifact_row: dict, parsed_payload: Any) -> tuple[dict, list[str]]:
    """Return a kind-specific summary dict and a (reserved) diagnostic list.

    Parameters
    ----------
    artifact_row:
        Raw artifact DB row dict from ``store.get_artifact()``.
    parsed_payload:
        Typed evidence object from ``cardre._evidence`` readers (e.g.
        ``WoeIvEvidence``, ``DataProfile``, ``ModelArtifact``).

    Returns
    -------
    ``(summary_dict, [])``
    """
    kind = _resolve_kind(artifact_row)
    role = artifact_row.get("role", "")

    if kind == "profile" and role == "split":
        kind = "split"

    summariser = _SUMMARISERS.get(kind)
    if summariser is None:
        return ({"unsupported_kind": True}, [])
    return (summariser(artifact_row, parsed_payload), [])
