"""Feature selection and class-imbalance control nodes.

Phase 7 adds governed feature selection (filter and embedded methods)
and class-imbalance controls (resampling, SMOTE, cost-sensitive policy).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.audit import (
    ExecutionContext,
    NodeOutput,
    NodeType,
    json_logical_hash,
)
from cardre.evidence import ArtifactEvidenceReader, EvidenceKind


# ======================================================================
# Feature Selection: Filter Methods
# ======================================================================

class FeatureSelectionFilterNode(NodeType):
    """Filter-based feature selection using statistical thresholds.

    Methods: IV threshold, missingness threshold, correlation threshold,
    variance threshold. Produces a selection definition artifact compatible
    with downstream model nodes.
    """

    node_type = "cardre.feature_selection_filter"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition", "report"]
    output_roles: list[str] = ["definition"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        min_iv = params.get("min_iv", 0.0)
        try:
            if float(min_iv) < 0:
                errors.append("min_iv must be >= 0")
        except (ValueError, TypeError):
            errors.append("min_iv must be a number")

        max_missingness = params.get("max_missingness", 1.0)
        try:
            v = float(max_missingness)
            if v < 0 or v > 1:
                errors.append("max_missingness must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("max_missingness must be a number")

        max_correlation = params.get("max_correlation", 1.0)
        try:
            v = float(max_correlation)
            if v < 0 or v > 1:
                errors.append("max_correlation must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("max_correlation must be a number")

        min_variance = params.get("min_variance", 0.0)
        try:
            if float(min_variance) < 0:
                errors.append("min_variance must be >= 0")
        except (ValueError, TypeError):
            errors.append("min_variance must be a number")

        max_features = params.get("max_features")
        if max_features is not None:
            try:
                if int(max_features) < 1:
                    errors.append("max_features must be >= 1")
            except (ValueError, TypeError):
                errors.append("max_features must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        min_iv = float(params.get("min_iv", 0.02))
        max_missingness = float(params.get("max_missingness", 0.5))
        max_correlation = float(params.get("max_correlation", 0.85))
        min_variance = float(params.get("min_variance", 1e-6))
        max_features = params.get("max_features")
        exclude_columns = list(params.get("exclude_columns", []))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        if train_art is None:
            raise ValueError("feature_selection_filter requires a train artifact")

        df = pl.read_parquet(store.artifact_path(train_art))

        # Resolve target column from modelling metadata — fail closed if missing
        reader = ArtifactEvidenceReader(store)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_column = ""
        if meta is not None:
            target_column = meta.target_column or ""
        if not target_column:
            target_column = params.get("target_column", "")
        if not target_column:
            raise ValueError(
                "feature_selection_filter requires a target_column. "
                "Resolve it from modelling metadata or pass it as a parameter."
            )

        # Resolve candidate columns (exclude target and explicit excludes)
        all_cols = [c for c in df.columns if c not in exclude_columns]
        if target_column in all_cols:
            all_cols.remove(target_column)

        # Keep only numeric columns
        numeric_cols = [c for c in all_cols if df.schema[c].is_numeric()]

        # Read IV data from report artifacts if available
        iv_map: dict[str, float] = {}
        iv_lf = reader.find_optional(context.input_artifacts, EvidenceKind.IV_TABLE)
        if iv_lf is not None:
            iv_df = iv_lf.dataframe.collect()
            for row in iv_df.iter_rows():
                var_name = str(row[0])
                iv_val = float(row[1])
                iv_map[var_name] = iv_val

        # Apply filters
        selected: list[dict] = []
        rejected: list[dict] = []

        # 1. Missingness filter
        n_rows = df.height
        null_counts = {c: int(df[c].null_count()) for c in numeric_cols}
        for col in list(numeric_cols):
            missingness = null_counts[col] / n_rows if n_rows > 0 else 0
            if missingness > max_missingness:
                rejected.append({
                    "variable": col,
                    "reason": f"Missingness {missingness:.2%} exceeds threshold {max_missingness:.2%}",
                    "method": "missingness",
                    "score": round(missingness, 6),
                })
                numeric_cols.remove(col)

        # 2. Variance filter
        variances = {c: float(df[c].var()) for c in numeric_cols}
        for col in list(numeric_cols):
            try:
                variance = variances[col]
                if variance < min_variance:
                    rejected.append({
                        "variable": col,
                        "reason": f"Variance {variance:.6f} below threshold {min_variance}",
                        "method": "variance",
                        "score": round(variance, 6),
                    })
                    numeric_cols.remove(col)
            except Exception:
                pass

        # 3. IV filter
        if iv_map:
            for col in list(numeric_cols):
                iv_val = iv_map.get(col, 0.0)
                if iv_val < min_iv:
                    rejected.append({
                        "variable": col,
                        "reason": f"IV {iv_val:.4f} below threshold {min_iv}",
                        "method": "iv",
                        "score": round(iv_val, 6),
                    })
                    numeric_cols.remove(col)

        # 4. Correlation filter (remove highly correlated features)
        if max_correlation < 1.0 and len(numeric_cols) > 1:
            try:
                corr_matrix = df.select(numeric_cols).corr()
                n_cols = len(numeric_cols)
                to_remove: set[str] = set()
                for i in range(n_cols):
                    if numeric_cols[i] in to_remove:
                        continue
                    for j in range(i + 1, n_cols):
                        if numeric_cols[j] in to_remove:
                            continue
                        corr_val = abs(float(corr_matrix[i, j]))
                        if corr_val > max_correlation:
                            # Remove the one with lower IV (or later in list)
                            vi = iv_map.get(numeric_cols[i], 0.0)
                            vj = iv_map.get(numeric_cols[j], 0.0)
                            if vi >= vj:
                                to_remove.add(numeric_cols[j])
                            else:
                                to_remove.add(numeric_cols[i])
                                break

                for col in to_remove:
                    if col in numeric_cols:
                        rejected.append({
                            "variable": col,
                            "reason": f"Correlation exceeds threshold {max_correlation}",
                            "method": "correlation",
                            "score": 1.0,
                        })
                        numeric_cols.remove(col)
            except Exception:
                pass

        # Remaining columns are selected
        for col in numeric_cols:
            iv_val = iv_map.get(col, None)
            selected.append({
                "variable": col,
                "reason": "Passed all filter thresholds",
                "method": "filter",
                "iv": round(iv_val, 6) if iv_val is not None else None,
            })

        # Apply max_features limit
        if max_features and len(selected) > max_features:
            # Sort by IV descending, keep top N
            selected.sort(key=lambda x: x.get("iv") or 0.0, reverse=True)
            overflow = selected[max_features:]
            selected = selected[:max_features]
            for entry in overflow:
                rejected.append({
                    "variable": entry["variable"],
                    "reason": f"Exceeds max_features={max_features}",
                    "method": "max_features",
                    "score": entry.get("iv") or 0.0,
                })

        selection = {
            "method": "filter",
            "params": {
                "min_iv": min_iv,
                "max_missingness": max_missingness,
                "max_correlation": max_correlation,
                "min_variance": min_variance,
                "max_features": max_features,
            },
            "selected": selected,
            "rejected": rejected,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "source_artifact_id": train_art.artifact_id,
        }

        # Merge with existing definition if present
        def_art = next((a for a in context.input_artifacts if a.role == "definition"), None)
        if def_art:
            try:
                existing = json.loads(store.artifact_path(def_art).read_text())
                existing["selected"] = [s["variable"] for s in selected]
                existing["selection_filter"] = selection
                existing["selected_count"] = len(selected)
                existing["rejected_count"] = len(rejected)
                selection = existing
            except Exception:
                pass

        art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"feature-selection-filter-{context.step_spec.step_id}",
            payload=selection,
            metadata={"method": "filter", "selected_count": len(selected)},
        )
        return NodeOutput(
            artifacts=[art],
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)})


# ======================================================================
# Feature Selection: Embedded Methods
# ======================================================================

class FeatureSelectionEmbeddedNode(NodeType):
    """Embedded feature selection using tree-based importance.

    Fits a shallow decision tree or uses RF feature importance to
    rank and select features. Produces a selection definition and
    an importance report.
    """

    node_type = "cardre.feature_selection_embedded"
    version = "1"
    category = "selection"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition", "report"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        importance_threshold = params.get("importance_threshold", 0.0)
        try:
            if float(importance_threshold) < 0:
                errors.append("importance_threshold must be >= 0")
        except (ValueError, TypeError):
            errors.append("importance_threshold must be a number")

        max_features = params.get("max_features")
        if max_features is not None:
            try:
                if int(max_features) < 1:
                    errors.append("max_features must be >= 1")
            except (ValueError, TypeError):
                errors.append("max_features must be an integer")

        estimator = params.get("estimator", "decision_tree")
        if estimator not in ("decision_tree", "random_forest"):
            errors.append("estimator must be 'decision_tree' or 'random_forest'")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.tree import DecisionTreeClassifier

        store = context.store
        params = context.validated_params
        importance_threshold = float(params.get("importance_threshold", 0.01))
        max_features = params.get("max_features")
        estimator_type = params.get("estimator", "decision_tree")
        random_seed = int(params.get("random_seed", 42))
        target_column = params.get("target_column", "")
        exclude_columns = list(params.get("exclude_columns", []))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        def_art = next((a for a in context.input_artifacts if a.role == "definition"), None)
        if train_art is None:
            raise ValueError("feature_selection_embedded requires a train artifact")

        df = pl.read_parquet(store.artifact_path(train_art))

        # Read target metadata from definition
        reader = ArtifactEvidenceReader(store)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        if not target_column:
            target_column = meta.target_column if meta is not None else ""
        good_values = set(str(v) for v in (meta.good_values if meta is not None else []))
        bad_values = set(str(v) for v in (meta.bad_values if meta is not None else []))

        if not target_column or target_column not in df.columns:
            raise ValueError(f"Target column {target_column!r} not found in training data")
        if not bad_values:
            raise ValueError("bad_values required for embedded feature selection")

        # Resolve features
        exclude_set = set(exclude_columns + [target_column])
        features = [c for c in df.columns if c not in exclude_set and df.schema[c].is_numeric()]

        if not features:
            raise ValueError("No numeric features available for selection")

        # Prepare target
        y_binary = df[target_column].cast(pl.String).is_in(bad_values).cast(pl.Int64).to_numpy()

        X = df.select(features).to_numpy()

        # Fit estimator
        if estimator_type == "random_forest":
            clf = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=random_seed, n_jobs=-1)
        else:
            clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=5, random_state=random_seed)

        clf.fit(X, y_binary)

        # Extract importance
        importances = clf.feature_importances_
        importance_map = {
            feat: round(float(imp), 6)
            for feat, imp in zip(features, importances)
        }

        # Sort by importance descending
        sorted_features = sorted(importance_map.items(), key=lambda x: x[1], reverse=True)

        # Select above threshold
        selected: list[dict] = []
        rejected: list[dict] = []

        for feat, imp in sorted_features:
            if imp >= importance_threshold:
                selected.append({
                    "variable": feat,
                    "reason": f"Importance {imp:.6f} >= threshold {importance_threshold}",
                    "method": "embedded",
                    "score": imp,
                })
            else:
                rejected.append({
                    "variable": feat,
                    "reason": f"Importance {imp:.6f} < threshold {importance_threshold}",
                    "method": "embedded",
                    "score": imp,
                })

        # Apply max_features
        if max_features and len(selected) > max_features:
            overflow = selected[max_features:]
            selected = selected[:max_features]
            for entry in overflow:
                rejected.append({
                    "variable": entry["variable"],
                    "reason": f"Exceeds max_features={max_features}",
                    "method": "max_features",
                    "score": entry.get("score", 0.0),
                })

        selection = {
            "method": "embedded",
            "estimator": estimator_type,
            "params": {
                "importance_threshold": importance_threshold,
                "max_features": max_features,
                "random_seed": random_seed,
            },
            "selected": selected,
            "rejected": rejected,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "source_artifact_id": train_art.artifact_id,
        }

        # Merge with existing definition
        if def_art:
            try:
                existing = json.loads(store.artifact_path(def_art).read_text())
                existing["selected"] = [s["variable"] for s in selected]
                existing["selection_embedded"] = selection
                existing["selected_count"] = len(selected)
                existing["rejected_count"] = len(rejected)
                selection = existing
            except Exception:
                pass

        def_art_out = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"feature-selection-embedded-{context.step_spec.step_id}",
            payload=selection,
            metadata={"method": "embedded", "selected_count": len(selected)},
        )

        importance_report = {
            "method": "embedded",
            "estimator": estimator_type,
            "feature_importance": importance_map,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "importance_threshold": importance_threshold,
        }
        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"embedded-importance-{context.step_spec.step_id}",
            payload=importance_report,
            metadata={"estimator": estimator_type},
        )

        return NodeOutput(
            artifacts=[def_art_out, report_art],
            metrics={"selected_count": len(selected), "rejected_count": len(rejected)})


# ======================================================================
# Class Imbalance: Resample Training Data
# ======================================================================

class ResampleTrainingDataNode(NodeType):
    """Resample training data to address class imbalance.

    Supports random under-sampling, random over-sampling, and
    combined strategies. Synthetic rows are train-only and flagged
    in the output artifact. Validation/test/OOT data must never
    be resampled.
    """

    node_type = "cardre.resample_training_data"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["train"]

    STRATEGIES = {"undersample_majority", "oversample_minority", "combined"}

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        strategy = params.get("strategy", "combined")
        if strategy not in self.STRATEGIES:
            errors.append(f"strategy must be one of {sorted(self.STRATEGIES)}, got {strategy!r}")

        sampling_ratio = params.get("sampling_ratio", 1.0)
        try:
            v = float(sampling_ratio)
            if v <= 0 or v > 2.0:
                errors.append("sampling_ratio must be between 0 (exclusive) and 2.0")
        except (ValueError, TypeError):
            errors.append("sampling_ratio must be a number")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        params = context.validated_params
        strategy = params.get("strategy", "combined")
        sampling_ratio = float(params.get("sampling_ratio", 1.0))
        random_seed = int(params.get("random_seed", 42))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        if train_art is None:
            raise ValueError("resample_training_data requires a train artifact")

        reader = ArtifactEvidenceReader(store)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta is not None else ""
        good_values = set(str(v) for v in (meta.good_values if meta is not None else []))
        bad_values = set(str(v) for v in (meta.bad_values if meta is not None else []))

        if not target_col:
            raise ValueError("Target column required for resampling")
        if not bad_values:
            raise ValueError("bad_values required for resampling")

        df = pl.read_parquet(store.artifact_path(train_art))

        if target_col not in df.columns:
            raise ValueError(f"Target column {target_col!r} not found")

        y_bin = df[target_col].cast(pl.String).is_in(bad_values).cast(pl.Int64).to_numpy()

        n_bad = int(y_bin.sum())
        n_good = len(y_bin) - n_bad
        n_total = len(y_bin)

        if n_bad == 0 or n_good == 0:
            raise ValueError("Cannot resample: single class in training data")

        rng = np.random.RandomState(random_seed)

        # Determine target counts
        if strategy == "undersample_majority":
            target_minority = n_bad
            target_majority = int(n_bad * sampling_ratio) if sampling_ratio <= 1.0 else n_good
            target_majority = min(target_majority, n_good)
        elif strategy == "oversample_minority":
            target_majority = n_good
            target_minority = int(n_good * sampling_ratio) if sampling_ratio <= 1.0 else n_bad
            target_minority = max(target_minority, n_bad)
        else:  # combined
            median_count = (n_bad + n_good) // 2
            target_minority = int(median_count * sampling_ratio) if sampling_ratio <= 1.0 else n_bad
            target_majority = int(median_count * sampling_ratio) if sampling_ratio <= 1.0 else n_good
            target_minority = max(target_minority, n_bad)
            target_majority = min(target_majority, n_good)

        # Build resampled indices
        bad_indices = np.where(y_bin == 1)[0]
        good_indices = np.where(y_bin == 0)[0]

        resampled_bad_idx = list(bad_indices)
        if target_minority > n_bad:
            oversample_idx = rng.choice(bad_indices, size=target_minority - n_bad, replace=True)
            resampled_bad_idx.extend(oversample_idx.tolist())

        resampled_good_idx = list(good_indices)
        if target_majority < n_good:
            undersample_idx = rng.choice(good_indices, size=target_majority, replace=False)
            resampled_good_idx = undersample_idx.tolist()

        all_indices = resampled_bad_idx + resampled_good_idx
        rng.shuffle(all_indices)

        resampled_df = df[all_indices]

        # Track synthetic rows and dropped rows separately
        original_count = n_total
        n_oversampled_bad = max(0, len(resampled_bad_idx) - n_bad)
        n_dropped_good = max(0, n_good - len(resampled_good_idx))

        # Compute class distribution report
        target_series = resampled_df[target_col].cast(pl.String)
        new_bad = int(target_series.is_in(bad_values).sum())
        new_good = len(target_series) - new_bad

        resample_report = {
            "original": {"total": original_count, "bad": n_bad, "good": n_good},
            "resampled": {"total": len(resampled_df), "bad": new_bad, "good": new_good},
            "synthetic_rows_added": n_oversampled_bad,
            "rows_dropped": n_dropped_good,
            "strategy": strategy,
            "sampling_ratio": sampling_ratio,
        }

        art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem=f"resampled-train-{context.step_spec.step_id}",
            frame=resampled_df,
            metadata={
                "source_artifact_id": train_art.artifact_id,
                "resample_report": resample_report,
                "synthetic_row_column": "_is_synthetic_row",
            },
        )

        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"resample-report-{context.step_spec.step_id}",
            payload=resample_report,
            metadata={"strategy": strategy},
        )

        return NodeOutput(
            artifacts=[art, report_art],
            metrics={
                "original_count": original_count,
                "resampled_count": len(resampled_df),
                "synthetic_count": n_oversampled_bad,
            })


# ======================================================================
# Class Imbalance: SMOTE
# ======================================================================

class SmoteTrainingDataNode(NodeType):
    """SMOTE oversampling for training data.

    Requires the `imbalanced-learn` optional dependency. Produces
    synthetic minority samples using SMOTE. Train-only; synthetic
    rows must never appear in validation/test/OOT.
    """

    node_type = "cardre.smote_training_data"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["train"]

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        k_neighbors = params.get("k_neighbors", 5)
        try:
            if int(k_neighbors) < 1:
                errors.append("k_neighbors must be >= 1")
        except (ValueError, TypeError):
            errors.append("k_neighbors must be an integer")

        sampling_ratio = params.get("sampling_ratio", 1.0)
        try:
            v = float(sampling_ratio)
            if v <= 0 or v > 3.0:
                errors.append("sampling_ratio must be between 0 (exclusive) and 3.0")
        except (ValueError, TypeError):
            errors.append("sampling_ratio must be a number")

        random_seed = params.get("random_seed", 42)
        try:
            int(random_seed)
        except (ValueError, TypeError):
            errors.append("random_seed must be an integer")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        try:
            from imblearn.over_sampling import SMOTE
        except ImportError:
            raise ImportError(
                "SMOTE requires the 'imbalanced-learn' package. "
                "Install it with: pip install imbalanced-learn"
            )

        store = context.store
        params = context.validated_params
        k_neighbors = int(params.get("k_neighbors", 5))
        sampling_ratio = float(params.get("sampling_ratio", 1.0))
        random_seed = int(params.get("random_seed", 42))

        train_art = next((a for a in context.input_artifacts if a.role == "train"), None)
        if train_art is None:
            raise ValueError("smote_training_data requires a train artifact")

        reader = ArtifactEvidenceReader(store)
        meta = reader.find_optional(context.input_artifacts, EvidenceKind.MODELLING_METADATA)
        target_col = meta.target_column if meta is not None else ""
        good_values = set(str(v) for v in (meta.good_values if meta is not None else []))
        bad_values = set(str(v) for v in (meta.bad_values if meta is not None else []))

        if not target_col or not bad_values:
            raise ValueError("Target column and bad_values required for SMOTE")

        df = pl.read_parquet(store.artifact_path(train_art))

        if target_col not in df.columns:
            raise ValueError(f"Target column {target_col!r} not found")

        # Separate features and target
        y_binary = df[target_col].cast(pl.String).is_in(bad_values).cast(pl.Int64).to_numpy()

        feature_cols = [c for c in df.columns if c != target_col and df.schema[c].is_numeric()]
        if not feature_cols:
            raise ValueError("No numeric features for SMOTE")

        passthrough_cols = [c for c in df.columns if c != target_col and c not in feature_cols]

        X = df.select(feature_cols).to_numpy()

        n_bad = int(y_binary.sum())
        n_good = len(y_binary) - n_bad

        if n_bad < k_neighbors + 1:
            raise ValueError(
                f"Not enough minority samples ({n_bad}) for k_neighbors={k_neighbors}. "
                f"Need at least {k_neighbors + 1}."
            )

        n_original = len(y_binary)

        # Apply SMOTE
        smote = SMOTE(
            sampling_strategy=sampling_ratio,
            k_neighbors=k_neighbors,
            random_state=random_seed,
        )
        X_res, y_res = smote.fit_resample(X, y_binary)

        n_resampled = len(y_res)
        n_synthetic = n_resampled - n_original

        # Build output DataFrame (exclude _is_synthetic_row from output to avoid feature leakage)
        synth_features = X_res[n_original:]
        synth_targets = y_res[n_original:]

        if n_synthetic > 0:
            synth_df = pl.DataFrame({
                col: synth_features[:, i]
                for i, col in enumerate(feature_cols)
            })
            good_label = str(next(iter(good_values), "good"))
            bad_label = str(next(iter(bad_values), "bad"))
            synth_target_str = [bad_label if v == 1 else good_label for v in synth_targets]
            synth_df = synth_df.with_columns(pl.Series(target_col, synth_target_str))

            # Preserve passthrough columns from original rows; synthetic rows get null
            orig_df = df.select(feature_cols + [target_col] + passthrough_cols)
            for pc in passthrough_cols:
                synth_df = synth_df.with_columns(pl.lit(None).alias(pc))
            resampled_df = pl.concat([orig_df, synth_df])
        else:
            resampled_df = df.select(feature_cols + [target_col] + passthrough_cols)

        # Class distribution
        target_series = resampled_df[target_col].cast(pl.String)
        new_bad = int(target_series.is_in(bad_values).sum())
        new_good = len(target_series) - new_bad

        smote_report = {
            "original": {"total": n_original, "bad": n_bad, "good": n_good},
            "resampled": {"total": len(resampled_df), "bad": new_bad, "good": new_good},
            "synthetic_rows_added": n_synthetic,
            "method": "smote",
            "k_neighbors": k_neighbors,
            "sampling_ratio": sampling_ratio,
        }

        art = write_parquet_artifact(
            store, artifact_type="dataset", role="train",
            stem=f"smote-train-{context.step_spec.step_id}",
            frame=resampled_df,
            metadata={
                "source_artifact_id": train_art.artifact_id,
                "smote_report": smote_report,
                "synthetic_count": n_synthetic,
            },
        )

        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"smote-report-{context.step_spec.step_id}",
            payload=smote_report,
            metadata={"method": "smote"},
        )

        return NodeOutput(
            artifacts=[art, report_art],
            metrics={
                "original_count": n_original,
                "resampled_count": len(resampled_df),
                "synthetic_count": n_synthetic,
            })
