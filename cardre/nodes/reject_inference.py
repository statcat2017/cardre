from __future__ import annotations

import time
from typing import Any

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

from cardre._evidence.kinds import EvidenceKind
from cardre._evidence.reader import ArtifactEvidenceReader
from cardre._evidence.schemas import SCHEMA_REJECT_INFERENCE_RESULT, SCHEMA_REJECT_POPULATION_CONFIG
from cardre.artifacts import write_json_artifact, write_parquet_artifact
from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType
from cardre.nodes.parameters import NodeParameterSchema

_RI_FINANCED = "_ri_financed"


class DefineRejectPopulationNode(NodeType):
    node_type = "cardre.define_reject_population"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "definition"]
    output_roles: list[str] = ["input", "definition"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        from cardre.nodes.parameters import MethodOption, NodeParameterSchema
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Define Reject Population",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    description="Classifies rows as financed, non-financed, or excluded using the sample definition and modelling metadata.",
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        exclusion_categories = params.get("exclusion_categories", {})
        if not isinstance(exclusion_categories, dict):
            errors.append("exclusion_categories must be a dict")
        else:
            for cat_name, spec in exclusion_categories.items():
                if not isinstance(spec, dict):
                    errors.append(f"exclusion_categories[{cat_name!r}] must be a dict with 'column' and 'values'")
                else:
                    if "column" not in spec:
                        errors.append(f"exclusion_categories[{cat_name!r}] missing required key 'column'")
                    if "values" not in spec or not isinstance(spec.get("values"), list):
                        errors.append(f"exclusion_categories[{cat_name!r}] missing required key 'values' (must be a list)")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        dataset_artifact = next(a for a in context.input_artifacts if a.role == "input")
        df = reader.read_dataframe(dataset_artifact)
        total_rows = df.height

        metadata = context.target_metadata()
        sample_def = reader.find(context.input_artifacts, EvidenceKind.SAMPLE_DEFINITION)

        target_column = metadata.target_column if metadata else ""
        good_values = {str(v) for v in (metadata.good_values if metadata else [])}
        bad_values = {str(v) for v in (metadata.bad_values if metadata else [])}
        indeterminate_values = {str(v) for v in (metadata.indeterminate_values if metadata else [])}

        sample_domain = sample_def.sample_domain
        rejection_source = sample_def.rejection_source
        rejection_column = sample_def.rejection_column

        if sample_domain == "ttd" and not rejection_source:
            available = [k for k in ("flag_column", "target_missing") if k]
            raise ValueError(
                f"TTD sample_domain requires rejection_source. "
                f"Set one of {available} in the sample-definition step params. "
                f"Got rejection_source={rejection_source!r}."
            )

        exclusion_categories = context.validated_params.get("exclusion_categories", {})
        exclusion_categories_out: dict[str, int] = {}

        target_str_expr = pl.col(target_column).cast(pl.Utf8)

        known_outcome_expr = target_str_expr.is_in(good_values | bad_values)
        is_indeterminate_expr = target_str_expr.is_in(indeterminate_values)

        exclusion_expr = pl.lit(False)
        for cat_name, spec in exclusion_categories.items():
            col_name = spec.get("column", "")
            cat_values = [str(v) for v in spec.get("values", [])]
            if col_name not in df.columns:
                raise ValueError(
                    f"Exclusion category {cat_name!r} references unknown column "
                    f"{col_name!r}. Available columns: {sorted(df.columns)}"
                )
            new_excl = pl.col(col_name).cast(pl.Utf8).is_in(cat_values).fill_null(False)
            exclusion_categories_out[cat_name] = int(df.select(new_excl.sum()).item())
            exclusion_expr = exclusion_expr | new_excl

        if sample_domain == "otb":
            financed_expr = ~exclusion_expr
        elif rejection_source == "target_missing":
            financed_expr = (~exclusion_expr) & pl.col(target_column).is_not_null() & known_outcome_expr
        elif rejection_source == "flag_column" and rejection_column:
            rejection_values_str = [str(v) for v in (sample_def.rejection_values or ["1", "true", "yes"])]
            flag_expr = pl.col(rejection_column).cast(pl.Utf8).is_in(rejection_values_str).fill_null(False)
            financed_expr = (~exclusion_expr) & (~flag_expr) & known_outcome_expr
        else:
            financed_expr = ~exclusion_expr

        financed_count = int(df.select(financed_expr.sum()).item())
        non_financed_count = int(df.select(((~exclusion_expr) & (~financed_expr)).sum()).item())
        indeterminate_count = int(df.select(is_indeterminate_expr.sum()).item())

        accepted_but_unlabeled_expr = (~exclusion_expr) & pl.col(target_column).is_not_null() & (~known_outcome_expr) & (~is_indeterminate_expr)
        unlabeled_accepted_count = int(df.select(accepted_but_unlabeled_expr.sum()).item())

        config = {
            "schema_version": SCHEMA_REJECT_POPULATION_CONFIG,
            "source_artifact_id": dataset_artifact.artifact_id,
            "total_rows": total_rows,
            "financed_rows": financed_count,
            "non_financed_rows": non_financed_count,
            "indeterminate_rows": indeterminate_count,
            "unlabeled_accepted_rows": unlabeled_accepted_count,
            "rejection_source": rejection_source or "target_missing",
            "rejection_column": rejection_column,
            "rejection_values": sample_def.rejection_values or None,
            "exclusion_categories": exclusion_categories_out,
            "observation_window_note": "",
        }

        df_out = df.with_columns(financed_expr.alias(_RI_FINANCED))
        df_out = df_out.filter(~exclusion_expr)

        dataset_out = write_parquet_artifact(
            store, artifact_type="dataset", role="input",
            stem=f"classified-{context.step_spec.step_id}",
            frame=df_out,
            metadata={
                "source_artifact_id": dataset_artifact.artifact_id,
                "rows_before": total_rows,
                "rows_after": df_out.height,
            },
        )

        config_art = write_json_artifact(
            store, artifact_type="definition", role="definition",
            stem=f"reject-population-{context.step_spec.step_id}",
            payload=config,
            metadata={"schema_version": SCHEMA_REJECT_POPULATION_CONFIG},
        )

        return NodeOutput(
            artifacts=[dataset_out, config_art],
            metrics={
                "total_rows": total_rows,
                "financed_rows": config["financed_rows"],
                "non_financed_rows": config["non_financed_rows"],
                "excluded_rows": int(df.select(exclusion_expr.sum()).item()),
            },
        )


class RejectInferenceNoneNode(NodeType):
    node_type = "cardre.reject_inference_none"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "definition"]
    output_roles: list[str] = ["input", "report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        from cardre.nodes.parameters import MethodOption, NodeParameterSchema
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Reject Inference — None",
            methods=[
                MethodOption(
                    id="ignore_rejects",
                    label="Ignore Rejects",
                    status="available",
                    description="Passes only financed rows downstream, excluding rejects. Assumes missing-at-random (MAR).",
                ),
            ],
        )

    def run(self, context: ExecutionContext) -> NodeOutput:
        store = context.store
        reader = ArtifactEvidenceReader(store)

        dataset_artifact = next(a for a in context.input_artifacts if a.role == "input")
        df = reader.read_dataframe(dataset_artifact)

        config = reader.find(context.input_artifacts, EvidenceKind.REJECT_POPULATION_CONFIG)

        n_non_financed = config.non_financed_rows

        df_financed = df.filter(pl.col(_RI_FINANCED))

        df_clean = df_financed.drop(_RI_FINANCED)

        dataset_out = write_parquet_artifact(
            store, artifact_type="dataset", role="input",
            stem=f"financed-only-{context.step_spec.step_id}",
            frame=df_clean,
            metadata={"source_artifact_id": dataset_artifact.artifact_id},
        )

        result = {
            "schema_version": SCHEMA_REJECT_INFERENCE_RESULT,
            "source_artifact_id": dataset_artifact.artifact_id,
            "method": "none",
            "method_params": {},
            "missingness_assumption": "MAR",
            "ignorability_note": (
                "Rows with unknown outcomes (non-financed) are excluded. "
                "This assumes p(y|x, financed) = p(y|x) — the missing-at-random "
                "assumption that financed applicants are representative of the "
                "full through-the-door population."
            ),
            "theoretical_limitations": [
                "Assumes financing decision is ignorable given observed features",
                "May underestimate bad rate if rejected applicants are riskier",
                "Selection bias is unverifiable under this assumption",
            ],
            "n_financed": config.financed_rows,
            "n_non_financed": n_non_financed,
            "n_inferred_good": 0,
            "n_inferred_bad": 0,
            "n_never_labeled": 0,
            "resampling_factor": None,
            "weight_summary": None,
            "convergence": None,
            "runtime_seconds": 0.0,
        }

        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"ri-none-{context.step_spec.step_id}",
            payload=result,
            metadata={"schema_version": SCHEMA_REJECT_INFERENCE_RESULT},
        )

        return NodeOutput(
            artifacts=[dataset_out, report_art],
            metrics={
                "method": "none",
                "n_financed": config.financed_rows,
                "n_non_financed": n_non_financed,
            },
        )


class RejectInferenceAugmentationNode(NodeType):
    node_type = "cardre.reject_inference_augmentation"
    version = "1"
    category = "transform"
    input_roles: list[str] = ["input", "definition"]
    output_roles: list[str] = ["input", "report"]

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        from cardre.nodes.parameters import (
            MethodOption,
            NodeParameterSchema,
            ParameterConstraint,
            ParameterDefinition,
        )
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Reject Inference — Augmentation",
            default_method="propensity_resampling",
            methods=[
                MethodOption(
                    id="propensity_resampling",
                    label="Propensity Resampling",
                    status="experimental",
                    description="Resamples financed rows with weights inversely proportional to propensity score band estimates. Assumes MAR. NOTE: fitted on ALL financed outcomes before train/test/oot split, which may leak holdout information into the development sample.",
                    params=[
                        ParameterDefinition(name="n_score_bands", label="Number of Score Bands", kind="integer", default=10, constraint=ParameterConstraint(min_value=1, max_value=100)),
                        ParameterDefinition(name="min_samples_per_band", label="Min Samples Per Band", kind="integer", default=30, constraint=ParameterConstraint(min_value=1)),
                        ParameterDefinition(name="band_min_p_financed", label="Min p(financed) Floor", kind="float", default=0.01, constraint=ParameterConstraint(min_value=0.001, max_value=1.0)),
                        ParameterDefinition(name="random_seed", label="Random Seed", kind="integer", default=42, constraint=ParameterConstraint(min_value=0)),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        n_score_bands = params.get("n_score_bands", 10)
        if not isinstance(n_score_bands, int) or n_score_bands < 1:
            errors.append("n_score_bands must be a positive integer")
        min_samples = params.get("min_samples_per_band", 30)
        if not isinstance(min_samples, int) or min_samples < 1:
            errors.append("min_samples_per_band must be a positive integer")
        min_p = params.get("band_min_p_financed", 0.01)
        if not isinstance(min_p, (int, float)) or min_p <= 0 or min_p > 1:
            errors.append("band_min_p_financed must be in (0, 1]")
        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        t0 = time.time()
        store = context.store
        reader = ArtifactEvidenceReader(store)
        params = context.validated_params

        dataset_artifact = next(a for a in context.input_artifacts if a.role == "input")
        df = reader.read_dataframe(dataset_artifact)

        config = reader.find(context.input_artifacts, EvidenceKind.REJECT_POPULATION_CONFIG)
        metadata = context.target_metadata()

        n_score_bands = int(params.get("n_score_bands", 10))
        min_samples_per_band = int(params.get("min_samples_per_band", 30))
        band_min_p_financed = float(params.get("band_min_p_financed", 0.01))
        random_seed = int(params.get("random_seed", 42))

        n_financed = config.financed_rows
        n_non_financed = config.non_financed_rows
        n_financed_unlabeled = 0

        if n_non_financed == 0:
            df_out = df.drop(_RI_FINANCED)
            dataset_out = write_parquet_artifact(
                store, artifact_type="dataset", role="input",
                stem=f"ri-aug-{context.step_spec.step_id}",
                frame=df_out,
                metadata={"source_artifact_id": dataset_artifact.artifact_id},
            )
            result_out = {
                "schema_version": SCHEMA_REJECT_INFERENCE_RESULT,
                "source_artifact_id": dataset_artifact.artifact_id,
                "method": "augmentation",
                "method_params": dict(params),
                "missingness_assumption": "MAR",
                "ignorability_note": "No non-financed rows; dataset passed through unchanged.",
                "theoretical_limitations": [],
                "n_financed": n_financed,
                "n_non_financed": 0,
                "n_inferred_good": 0,
                "n_inferred_bad": 0,
                "n_never_labeled": 0,
                "resampling_factor": None,
                "weight_summary": None,
                "convergence": None,
                "runtime_seconds": round(time.time() - t0, 4),
            }
            report_art = write_json_artifact(
                store, artifact_type="report", role="report",
                stem=f"ri-aug-{context.step_spec.step_id}",
                payload=result_out,
                metadata={"schema_version": SCHEMA_REJECT_INFERENCE_RESULT},
            )
            return NodeOutput(
                artifacts=[dataset_out, report_art],
                metrics={"method": "augmentation", "n_financed": n_financed, "resampled": 0},
            )

        target_column = metadata.target_column if metadata else ""
        good_values = {str(v) for v in (metadata.good_values if metadata else [])}
        bad_values = {str(v) for v in (metadata.bad_values if metadata else [])}
        all_known = good_values | bad_values

        numeric_cols = [c for c in df.columns
                        if df.schema[c].is_numeric()
                        and c not in (target_column, _RI_FINANCED)]

        df_financed = df.filter(pl.col(_RI_FINANCED))
        target_str = df_financed[target_column].cast(pl.Utf8)
        has_known_target = target_str.is_in(all_known)
        df_financed_known = df_financed.filter(has_known_target)
        n_financed_unlabeled = int((~has_known_target).sum())

        y_financed = (
            df_financed_known[target_column]
            .cast(pl.Utf8)
            .is_in(bad_values)
            .cast(pl.Int64)
            .to_list()
        )

        X_financed = df_financed_known.select(numeric_cols).to_numpy()
        X_all = df.select(numeric_cols).to_numpy()

        propensity_model = LogisticRegression(max_iter=1000, random_state=random_seed)
        propensity_model.fit(X_financed, y_financed)
        scores = propensity_model.predict_proba(X_all)[:, 1]

        scores_col = pl.Series("_ri_score", scores)
        df_scored = df.with_columns(scores_col)

        n_total = df_scored.height
        n_bands = max(1, min(n_score_bands, n_total // min_samples_per_band))

        band_edges = [
            float(df_scored.select(pl.col("_ri_score").quantile(i / n_bands)).item())
            for i in range(1, n_bands)
        ]
        band_edges = sorted(set(band_edges))

        def _band_label(s: float) -> int:
            for i, edge in enumerate(band_edges):
                if s <= edge:
                    return i
            return len(band_edges)

        band_col = pl.Series("_ri_band", [_band_label(s) for s in scores])

        df_banded = df_scored.with_columns(band_col)

        band_stats: list[dict[str, Any]] = []
        weights: pl.Series | pl.Expr = pl.Series("_ri_weight", [0.0] * n_total)

        for band_idx in range(n_bands):
            in_band = df_banded.filter(pl.col("_ri_band") == band_idx)
            n_in_band = in_band.height
            n_financed_in_band = int(in_band.select(pl.col(_RI_FINANCED).sum()).item())
            p_k = n_financed_in_band / max(n_in_band, 1)
            p_k_clamped = max(p_k, band_min_p_financed)

            w_val = 1.0 / p_k_clamped
            band_mask = pl.col("_ri_band") == band_idx
            weights = pl.when(band_mask & pl.col(_RI_FINANCED)).then(w_val).otherwise(weights).alias("_ri_weight")
            band_stats.append({
                "band": band_idx,
                "n_total": n_in_band,
                "n_financed": n_financed_in_band,
                "p_financed": round(p_k, 4),
                "weight": round(w_val, 4),
            })

        df_resample = df_banded.with_columns(weights)

        financed_mask = df_resample.select(pl.col(_RI_FINANCED)).to_series().to_list()
        target_known = df_resample.select(pl.col(target_column).cast(pl.Utf8).is_in(all_known)).to_series().to_list()
        eligible_mask = [f and k for f, k in zip(financed_mask, target_known, strict=False)]
        weight_vals = df_resample.select(pl.col("_ri_weight")).to_series().to_list()
        financed_indices = [i for i, e in enumerate(eligible_mask) if e]

        if not financed_indices:
            raise ValueError("No financed rows available for resampling")

        financed_weights = [weight_vals[i] for i in financed_indices]
        total_w = sum(financed_weights)
        norm_weights = [w / total_w for w in financed_weights]

        rng_np = np.random.default_rng(random_seed)
        sampled_indices = sorted(rng_np.choice(financed_indices, size=n_financed, p=norm_weights, replace=True))

        resample_factor = float(n_financed) / max(n_financed, 1)

        df_with_idx = df_resample.with_columns(pl.Series("_ri_idx", range(n_total)))
        df_augmented = pl.concat([df_with_idx[i: i + 1] for i in sampled_indices])
        df_augmented = df_augmented.drop(["_ri_score", "_ri_band", "_ri_weight", "_ri_idx"])

        df_out = df_augmented.drop(_RI_FINANCED)

        dataset_out = write_parquet_artifact(
            store, artifact_type="dataset", role="input",
            stem=f"ri-aug-{context.step_spec.step_id}",
            frame=df_out,
            metadata={"source_artifact_id": dataset_artifact.artifact_id},
        )

        weight_vals_financed = [weight_vals[i] for i in financed_indices]
        weight_summary = {
            "min": round(min(weight_vals_financed), 4) if weight_vals_financed else 0.0,
            "max": round(max(weight_vals_financed), 4) if weight_vals_financed else 0.0,
            "mean": round(sum(weight_vals_financed) / max(len(weight_vals_financed), 1), 4),
            "std": round(
                (sum((w - sum(weight_vals_financed) / max(len(weight_vals_financed), 1)) ** 2
                     for w in weight_vals_financed) / max(len(weight_vals_financed), 1)) ** 0.5
                if len(weight_vals_financed) > 1 else 0.0, 4),
        }

        runtime = round(time.time() - t0, 4)

        result_out = {
            "schema_version": SCHEMA_REJECT_INFERENCE_RESULT,
            "source_artifact_id": dataset_artifact.artifact_id,
            "method": "augmentation",
            "method_params": {
                "n_score_bands": n_score_bands,
                "min_samples_per_band": min_samples_per_band,
                "band_min_p_financed": band_min_p_financed,
                "random_seed": random_seed,
            },
            "missingness_assumption": "MAR",
            "ignorability_note": (
                "Resampling-based augmentation with propensity score bands. "
                "Financed rows are resampled with weights inversely proportional "
                "to the estimated probability of being financed within their score band. "
                "Assumes p(financed|x,y) = p(financed|x) — missing-at-random given features."
            ),
            "theoretical_limitations": [
                "Assumes p(financed|x) > 0 for all x in the population",
                "Band-based estimation may pool dissimilar applicants",
                "Resampling introduces Monte Carlo variance",
                "Propensity model is finite-sample; may not generalize to entire reject population",
            ],
            "n_financed": n_financed,
            "n_non_financed": n_non_financed,
            "n_inferred_good": 0,
            "n_inferred_bad": 0,
            "n_never_labeled": n_financed_unlabeled,
            "resampling_factor": round(resample_factor, 4),
            "weight_summary": weight_summary,
            "convergence": None,
            "runtime_seconds": runtime,
        }

        report_art = write_json_artifact(
            store, artifact_type="report", role="report",
            stem=f"ri-aug-{context.step_spec.step_id}",
            payload=result_out,
            metadata={"schema_version": SCHEMA_REJECT_INFERENCE_RESULT},
        )

        return NodeOutput(
            artifacts=[dataset_out, report_art],
            metrics={
                "method": "augmentation",
                "n_financed": n_financed,
                "n_non_financed": n_non_financed,
                "resampled": len(sampled_indices),
                "unlabeled_financed": n_financed_unlabeled,
                "n_bands": n_bands,
            },
        )


__all__ = [
    "DefineRejectPopulationNode",
    "RejectInferenceAugmentationNode",
    "RejectInferenceNoneNode",
]
