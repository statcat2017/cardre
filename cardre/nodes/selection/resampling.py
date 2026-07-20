from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes._training_utils import prepare_supervised_training_data
from cardre.nodes.contracts import NodeType


class ResampleTrainingDataNode(NodeType):
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

        prepared = prepare_supervised_training_data(
            context,
            operation="resample_training_data",
        )
        df = prepared.frame
        target_col = prepared.target_column
        y_bin = prepared.y_binary
        bad_values = prepared.bad_values
        train_art = context.require_train_artifact("resample_training_data")

        n_bad = int(y_bin.sum())
        n_good = len(y_bin) - n_bad
        n_total = len(y_bin)

        if n_bad == 0 or n_good == 0:
            raise ValueError("Cannot resample: single class in training data")

        rng = np.random.RandomState(random_seed)

        if strategy == "undersample_majority":
            target_minority = n_bad
            target_majority = int(n_bad * sampling_ratio) if sampling_ratio <= 1.0 else n_good
            target_majority = min(target_majority, n_good)
        elif strategy == "oversample_minority":
            target_majority = n_good
            target_minority = int(n_good * sampling_ratio) if sampling_ratio <= 1.0 else n_bad
            target_minority = max(target_minority, n_bad)
        else:
            median_count = (n_bad + n_good) // 2
            target_minority = int(median_count * sampling_ratio) if sampling_ratio <= 1.0 else n_bad
            target_majority = int(median_count * sampling_ratio) if sampling_ratio <= 1.0 else n_good
            target_minority = max(target_minority, n_bad)
            target_majority = min(target_majority, n_good)

        bad_indices = np.where(y_bin == 1)[0]
        good_indices = np.where(y_bin == 0)[0]

        selected_bad_idx = bad_indices
        selected_good_idx = (
            rng.choice(good_indices, size=target_majority, replace=False)
            if target_majority < n_good
            else good_indices
        )
        extra_indices = (
            rng.choice(bad_indices, size=target_minority - n_bad, replace=True)
            if target_minority > n_bad
            else np.array([], dtype=int)
        )

        base_indices = np.concatenate([selected_bad_idx, selected_good_idx])
        all_indices = np.concatenate([base_indices, extra_indices])

        incoming_raw = df.get_column("_is_synthetic_row").to_numpy() if "_is_synthetic_row" in df.columns else None
        incoming_base = incoming_raw[base_indices] if incoming_raw is not None else np.zeros(len(base_indices), dtype=bool)
        synthetic_flags = np.concatenate([
            incoming_base,
            np.ones(len(extra_indices), dtype=bool),
        ])

        perm = rng.permutation(len(all_indices))
        resampled_df = df[all_indices[perm]].with_columns(
            pl.Series("_is_synthetic_row", synthetic_flags[perm])
        )

        n_oversampled_bad = len(extra_indices)
        n_dropped_good = max(0, n_good - len(selected_good_idx))
        original_count = n_total

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
