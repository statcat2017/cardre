"""Fairness, proxy risk, and alternative-data governance nodes.

Phase 9 adds concrete governance gates for fairness and alternative-data usage.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import polars as pl

from cardre.artifacts import make_fingerprint, write_json_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
)

# Minimum group size for reliable metrics
MIN_GROUP_SIZE = 30


class FairnessReportNode(NodeType):
    """Compute fairness metrics across sensitive groups.

    Produces group-level metrics: approval rate, bad rate, error rates,
    score distribution by sensitive column. Suppresses small groups
    as insufficient_evidence.
    """

    node_type = "cardre.fairness_report"
    version = "1"
    category = "report"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        sensitive_columns = params.get("sensitive_columns", [])
        if not isinstance(sensitive_columns, list):
            errors.append("sensitive_columns must be a list")
        elif len(sensitive_columns) == 0:
            errors.append("sensitive_columns must have at least one entry")

        min_group_size = params.get("min_group_size", MIN_GROUP_SIZE)
        try:
            if int(min_group_size) < 5:
                errors.append("min_group_size must be >= 5")
        except (ValueError, TypeError):
            errors.append("min_group_size must be an integer")

        cutoff = params.get("cutoff", 0.5)
        try:
            v = float(cutoff)
            if v < 0 or v > 1:
                errors.append("cutoff must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("cutoff must be a number")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        sensitive_columns = list(params.get("sensitive_columns", []))
        min_group_size = int(params.get("min_group_size", MIN_GROUP_SIZE))
        cutoff = float(params.get("cutoff", 0.5))

        meta_art = None
        for a in context.input_artifacts:
            if a.role == "definition":
                try:
                    p = json.loads(store.artifact_path(a).read_text())
                    if "target_column" in p and "good_values" in p:
                        meta_art = a
                        break
                except Exception:
                    continue

        meta = {}
        if meta_art:
            meta = json.loads(store.artifact_path(meta_art).read_text())
        target_col = meta.get("target_column", "")
        good = set(str(v) for v in meta.get("good_values", []))
        bad = set(str(v) for v in meta.get("bad_values", []))

        data_arts = [a for a in context.input_artifacts if a.role in ("train", "test", "oot")]
        report: dict = {
            "sensitive_columns": sensitive_columns,
            "min_group_size": min_group_size,
            "cutoff": cutoff,
            "roles": {},
        }

        for data_art in data_arts:
            role = data_art.role
            df = pl.read_parquet(store.artifact_path(data_art))
            role_report: dict[str, Any] = {"row_count": df.height}

            if "predicted_bad_probability" not in df.columns:
                role_report["error"] = "Missing predicted_bad_probability"
                report["roles"][role] = role_report
                continue

            y_prob = df["predicted_bad_probability"].to_list()
            y_pred = [1 if p >= cutoff else 0 for p in y_prob]

            target_available = bool(target_col and target_col in df.columns and bad)
            y_bin = None
            if target_available:
                y_raw = df[target_col].cast(pl.String).to_list()
                y_bin = [1 if str(v) in bad else 0 for v in y_raw]

            scores = df["score"].to_list() if "score" in df.columns else y_prob

            group_metrics: dict[str, Any] = {}
            for col in sensitive_columns:
                if col not in df.columns:
                    group_metrics[col] = {"error": f"Column {col!r} not found"}
                    continue

                groups = df[col].cast(pl.String).unique().to_list()
                col_report: dict[str, Any] = {}

                for group_val in groups:
                    mask = df[col].cast(pl.String) == group_val
                    indices = [i for i, m in enumerate(mask) if m]
                    n_group = len(indices)

                    if n_group < min_group_size:
                        col_report[group_val] = {
                            "n": n_group,
                            "status": "insufficient_evidence",
                            "message": f"Group size {n_group} < min_group_size {min_group_size}",
                        }
                        continue

                    group_pred = [y_pred[i] for i in indices]
                    group_scores = [scores[i] for i in indices]
                    group_probs = [y_prob[i] for i in indices]

                    approval_rate = round(1 - sum(group_pred) / n_group, 4) if n_group > 0 else 0.0

                    score_dist = {
                        "mean": round(float(np.mean(group_scores)), 2),
                        "median": round(float(np.median(group_scores)), 2),
                        "p25": round(float(np.percentile(group_scores, 25)), 2),
                        "p75": round(float(np.percentile(group_scores, 75)), 2),
                    }

                    entry: dict[str, Any] = {
                        "n": n_group,
                        "approval_rate": approval_rate,
                        "score_distribution": score_dist,
                    }

                    if y_bin is not None:
                        group_y = [y_bin[i] for i in indices]
                        n_bad_group = sum(group_y)
                        n_good_group = n_group - n_bad_group

                        entry["n_bad"] = n_bad_group
                        entry["n_good"] = n_good_group
                        entry["bad_rate"] = round(n_bad_group / n_group, 4) if n_group > 0 else 0.0

                        # Error rates
                        tp = sum(1 for a, p in zip(group_y, group_pred) if a == 1 and p == 1)
                        fp = sum(1 for a, p in zip(group_y, group_pred) if a == 0 and p == 1)
                        fn = sum(1 for a, p in zip(group_y, group_pred) if a == 1 and p == 0)
                        tn = sum(1 for a, p in zip(group_y, group_pred) if a == 0 and p == 0)

                        entry["precision"] = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
                        entry["recall"] = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
                        entry["specificity"] = round(tn / (tn + fp), 4) if (tn + fp) > 0 else 0.0
                        entry["false_positive_rate"] = round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0

                    col_report[group_val] = entry

                group_metrics[col] = col_report

            role_report["group_metrics"] = group_metrics
            role_report["target_available"] = target_available
            if not target_available:
                role_report["target_warning"] = "Target column or bad_values unavailable; outcome-based metrics omitted."
            report["roles"][role] = role_report

        # Cross-group parity summary
        report["parity_summary"] = self._compute_parity_summary(report["roles"], sensitive_columns)

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"fairness-report-{context.step_spec.step_id}",
            payload=report,
            metadata={"sensitive_columns": sensitive_columns},
        )
        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[art],
        )
        return NodeOutput(artifacts=[art], metrics={"role_count": len(data_arts)}, execution_fingerprint=fp)

    def _compute_parity_summary(self, roles: dict, sensitive_columns: list[str]) -> dict:
        """Compute approval parity and error parity across groups.

        Splits approval parity (always computed when groups exist) from
        outcome-based parity (bad-rate, FPR) which requires target labels.
        Column-level errors are excluded from parity calculations.
        """
        summary: dict[str, Any] = {}

        for col in sensitive_columns:
            col_summary: dict[str, Any] = {}
            for role_name, role_data in roles.items():
                group_metrics = role_data.get("group_metrics", {}).get(col, {})
                valid_groups = {
                    k: v for k, v in group_metrics.items()
                    if isinstance(v, dict) and v.get("status") != "insufficient_evidence"
                       and "error" not in v
                }
                if not valid_groups:
                    continue

                approval_rates = [g["approval_rate"] for g in valid_groups.values()]
                outcome_available = all("bad_rate" in g for g in valid_groups.values())

                if len(approval_rates) >= 2:
                    entry: dict[str, Any] = {
                        "group_count": len(valid_groups),
                        "max_approval_rate_difference": round(
                            max(approval_rates) - min(approval_rates), 4,
                        ),
                    }

                    if outcome_available:
                        bad_rates = [g["bad_rate"] for g in valid_groups.values()]
                        fprs = [g["false_positive_rate"] for g in valid_groups.values()]
                        entry["max_bad_rate_difference"] = round(max(bad_rates) - min(bad_rates), 4)
                        entry["max_false_positive_rate_difference"] = round(max(fprs) - min(fprs), 4)

                    col_summary[role_name] = entry

            if col_summary:
                summary[col] = col_summary

        return summary


class ProxyRiskReportNode(NodeType):
    """Check for proxy risk from sensitive or prohibited variables.

    Computes correlation and feature importance overlap between
    sensitive columns and model features to detect proxy risk.
    """

    node_type = "cardre.proxy_risk_report"
    version = "1"
    category = "report"
    input_roles: list[str] = ["train", "model", "definition"]
    output_roles: list[str] = ["report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        sensitive_columns = params.get("sensitive_columns", [])
        if not isinstance(sensitive_columns, list):
            errors.append("sensitive_columns must be a list")

        correlation_threshold = params.get("correlation_threshold", 0.3)
        try:
            v = float(correlation_threshold)
            if v < 0 or v > 1:
                errors.append("correlation_threshold must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("correlation_threshold must be a number")

        importance_threshold = params.get("importance_threshold", 0.05)
        try:
            v = float(importance_threshold)
            if v < 0 or v > 1:
                errors.append("importance_threshold must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("importance_threshold must be a number")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        sensitive_columns = list(params.get("sensitive_columns", []))
        correlation_threshold = float(params.get("correlation_threshold", 0.3))
        importance_threshold = float(params.get("importance_threshold", 0.05))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        model_art = next((a for a in context.input_artifacts if a.role == "model"), None)

        report: dict[str, Any] = {
            "sensitive_columns": sensitive_columns,
            "correlation_threshold": correlation_threshold,
            "importance_threshold": importance_threshold,
            "proxy_flags": [],
        }

        # Load model features and importance
        model_features: list[str] = []
        feature_importance: dict[str, float] = {}
        if model_art:
            try:
                model = json.loads(store.artifact_path(model_art).read_text())
                model_features = model.get("features", [])
                feature_importance = model.get("model_payload", {}).get("feature_importance", {})
            except Exception:
                pass

        # Load training data
        if train_art:
            try:
                df = pl.read_parquet(store.artifact_path(train_art))
            except Exception:
                df = None
        else:
            df = None

        for col in sensitive_columns:
            if df is None or col not in df.columns:
                report["proxy_flags"].append({
                    "sensitive_column": col,
                    "status": "column_not_found",
                    "message": f"Sensitive column {col!r} not found in training data",
                })
                continue

            # Correlation check
            correlations: dict[str, float] = {}
            if df[col].dtype.is_numeric():
                for feat in model_features:
                    if feat in df.columns and df[feat].dtype.is_numeric():
                        try:
                            corr = abs(float(df.select(pl.corr(col, feat)).item()))
                            if not np.isnan(corr):
                                correlations[feat] = round(corr, 4)
                        except Exception:
                            pass

            high_corr_features = [
                f for f, c in correlations.items() if c > correlation_threshold
            ]

            # Importance check (if sensitive column appears in feature importance)
            sensitive_importance = feature_importance.get(col, 0.0)

            # Check if any model feature is highly correlated with sensitive column
            proxy_features = []
            for feat in model_features:
                if feat == col:
                    proxy_features.append({"feature": feat, "reason": "directly_sensitive"})
                elif feat in correlations and correlations[feat] > correlation_threshold:
                    proxy_features.append({
                        "feature": feat,
                        "reason": f"correlation {correlations[feat]:.4f} > {correlation_threshold}",
                        "correlation": correlations[feat],
                    })

            risk_level = "low"
            if proxy_features:
                risk_level = "high"
            elif sensitive_importance > importance_threshold:
                risk_level = "medium"

            flag = {
                "sensitive_column": col,
                "risk_level": risk_level,
                "correlations_with_features": correlations,
                "high_correlation_features": high_corr_features,
                "sensitive_feature_importance": round(sensitive_importance, 6),
                "proxy_features": proxy_features,
            }

            if risk_level == "high":
                flag["message"] = (
                    f"High proxy risk: {len(proxy_features)} model feature(s) are "
                    f"correlated with sensitive column {col!r}"
                )
            elif risk_level == "medium":
                flag["message"] = (
                    f"Medium proxy risk: sensitive column {col!r} has "
                    f"importance {sensitive_importance:.4f}"
                )
            else:
                flag["message"] = f"Low proxy risk for sensitive column {col!r}"

            report["proxy_flags"].append(flag)

        # Overall risk assessment
        risk_levels = [f["risk_level"] for f in report["proxy_flags"]]
        if "high" in risk_levels:
            report["overall_risk"] = "high"
        elif "medium" in risk_levels:
            report["overall_risk"] = "medium"
        else:
            report["overall_risk"] = "low"

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"proxy-risk-report-{context.step_spec.step_id}",
            payload=report,
            metadata={"overall_risk": report["overall_risk"]},
        )
        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[art],
        )
        return NodeOutput(
            artifacts=[art],
            metrics={"overall_risk": report["overall_risk"]},
            execution_fingerprint=fp,
        )


class AlternativeDataManifestNode(NodeType):
    """Record provenance, consent, and usage evidence for alternative data.

    Produces a structured manifest with source, consent basis, permitted
    use, retention, refresh date, missingness, and coverage evidence.
    """

    node_type = "cardre.alternative_data_manifest"
    version = "1"
    category = "report"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        entries = params.get("data_sources", [])
        if not isinstance(entries, list):
            errors.append("data_sources must be a list")
            return errors

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"data_sources[{i}] must be a dict")
                continue
            for field in ("source_name", "consent_basis", "permitted_use"):
                if not entry.get(field):
                    errors.append(f"data_sources[{i}] missing required field {field!r}")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        data_sources = list(params.get("data_sources", []))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        df = None
        if train_art:
            try:
                df = pl.read_parquet(store.artifact_path(train_art))
            except Exception:
                pass

        # Compute coverage and missingness per source
        source_evidence: list[dict] = []
        for src in data_sources:
            columns = list(src.get("columns", []))
            coverage: dict[str, Any] = {}
            missingness: dict[str, Any] = {}

            if df is not None:
                n_rows = df.height
                for col in columns:
                    if col in df.columns:
                        null_count = df[col].null_count()
                        coverage[col] = round(1 - null_count / n_rows, 4) if n_rows > 0 else 0.0
                        missingness[col] = round(null_count / n_rows, 4) if n_rows > 0 else 0.0
                    else:
                        coverage[col] = 0.0
                        missingness[col] = 1.0

            evidence = {
                "source_name": src.get("source_name", ""),
                "source_type": src.get("source_type", "alternative"),
                "consent_basis": src.get("consent_basis", ""),
                "permitted_use": src.get("permitted_use", ""),
                "retention_policy": src.get("retention_policy", ""),
                "refresh_date": src.get("refresh_date", ""),
                "data_owner": src.get("data_owner", ""),
                "columns": columns,
                "coverage": coverage,
                "missingness": missingness,
                "recency_days": src.get("recency_days"),
                "privacy_level": src.get("privacy_level", "unknown"),
            }
            source_evidence.append(evidence)

        manifest = {
            "data_sources": source_evidence,
            "total_sources": len(source_evidence),
            "consent_verified": all(s.get("consent_basis") for s in source_evidence),
            "all_use_permitted": all(s.get("permitted_use") for s in source_evidence),
        }

        # Check if promotion should be blocked
        blocks: list[str] = []
        if not manifest["consent_verified"]:
            blocks.append("One or more data sources lack consent basis")
        if not manifest["all_use_permitted"]:
            blocks.append("One or more data sources lack permitted use declaration")
        manifest["promotion_blocks"] = blocks
        manifest["champion_eligible"] = len(blocks) == 0

        art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"alt-data-manifest-{context.step_spec.step_id}",
            payload=manifest,
            metadata={
                "total_sources": len(source_evidence),
                "champion_eligible": manifest["champion_eligible"],
            },
        )
        fp = make_fingerprint(
            plan_version_id=context.plan_version_id,
            step_id=context.step_spec.step_id,
            node_type=self.node_type, node_version=self.version,
            params_hash=context.step_spec.params_hash,
            parent_run_steps=context.parent_run_steps,
            input_artifacts=context.input_artifacts,
            output_artifacts=[art],
        )
        return NodeOutput(
            artifacts=[art],
            metrics={"total_sources": len(source_evidence)},
            execution_fingerprint=fp,
        )
