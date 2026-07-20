from __future__ import annotations

from typing import Any

import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes._training_utils import prepare_supervised_training_data
from cardre.nodes.contracts import NodeType


class SmoteTrainingDataNode(NodeType):
    node_type = "cardre.smote_training_data"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["train"]
    optional_dependencies: list[str] = ["imbalance"]

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
            ) from None

        store = context.store
        params = context.validated_params
        k_neighbors = int(params.get("k_neighbors", 5))
        sampling_ratio = float(params.get("sampling_ratio", 1.0))
        random_seed = int(params.get("random_seed", 42))

        prepared = prepare_supervised_training_data(
            context,
            operation="smote_training_data",
        )
        df = prepared.frame
        target_col = prepared.target_column
        good_values = prepared.good_values
        bad_values = prepared.bad_values
        y_binary = prepared.y_binary
        feature_cols = prepared.feature_columns(params)
        train_art = context.require_train_artifact("smote_training_data")

        passthrough_cols = [
            column
            for column in df.columns
            if column not in set(feature_cols) | {target_col, "_is_synthetic_row"}
        ]

        n_bad = int(y_binary.sum())
        n_good = len(y_binary) - n_bad

        if n_bad < k_neighbors + 1:
            raise ValueError(
                f"Not enough minority samples ({n_bad}) for k_neighbors={k_neighbors}. "
                f"Need at least {k_neighbors + 1}."
            )

        n_original = len(y_binary)

        X = df.select(feature_cols).to_numpy()
        smote = SMOTE(
            sampling_strategy=sampling_ratio,
            k_neighbors=k_neighbors,
            random_state=random_seed,
        )
        X_res, y_res = smote.fit_resample(X, y_binary)

        n_resampled = len(y_res)
        n_synthetic = n_resampled - n_original

        incoming_flag_col = "_is_synthetic_row"
        has_incoming = incoming_flag_col in df.columns
        base_select = feature_cols + [target_col] + passthrough_cols
        if incoming_flag_col in base_select:
            base_select.remove(incoming_flag_col)

        if has_incoming:
            orig_df = df.select(base_select + [incoming_flag_col])
        else:
            orig_df = df.select(base_select).with_columns(
                pl.lit(False).alias(incoming_flag_col)
            )

        if n_synthetic > 0:
            synth_features = X_res[n_original:]
            synth_targets = y_res[n_original:]
            synth_df = pl.DataFrame({
                col: synth_features[:, i]
                for i, col in enumerate(feature_cols)
            })
            good_label = str(next(iter(good_values), "good"))
            bad_label = str(next(iter(bad_values), "bad"))
            synth_target_str = [bad_label if v == 1 else good_label for v in synth_targets]
            synth_df = synth_df.with_columns(
                pl.Series(target_col, synth_target_str),
            )
            for pc in passthrough_cols:
                synth_df = synth_df.with_columns(pl.lit(None).alias(pc))
            synth_df = synth_df.with_columns(
                pl.lit(True).alias("_is_synthetic_row")
            )
            resampled_df = pl.concat([orig_df, synth_df])
        else:
            resampled_df = orig_df

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
                "synthetic_row_column": "_is_synthetic_row",
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
