from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from cardre.domain.diagnostics import JsonDict
from cardre.domain.evidence.kinds import EvidenceKind
from cardre.nodes.contracts import (
    ArtifactContract,
    ArtifactRoleSpec,
    NodeContext,
    NodeDefinition,
    NodeResult,
    NodeType,
)
from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


class ThresholdOptimizationNode(NodeType):
    node_type = "cardre.threshold_optimization"
    version = "1"
    category = "apply"
    input_roles: list[str] = ["train", "test", "oot", "definition"]
    output_roles: list[str] = ["report"]

    OBJECTIVES = {"youden", "max_f1", "max_g_mean", "cost_minimize"}

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Threshold optimization",
            methods=[
                MethodOption(
                    id="default",
                    label="Default",
                    status="available",
                    params=[
                        ParameterDefinition(
                            name="objective",
                            label="Objective",
                            kind="enum",
                            default="youden",
                            constraint=ParameterConstraint(
                                enum_values=["youden", "max_f1", "max_g_mean", "cost_minimize"],
                            ),
                            help_text="Optimization objective for threshold selection.",
                        ),
                        ParameterDefinition(
                            name="n_thresholds",
                            label="Number of thresholds",
                            kind="integer",
                            default=200,
                            constraint=ParameterConstraint(min_value=10),
                            help_text="Number of evenly-spaced threshold candidates to evaluate.",
                        ),
                        ParameterDefinition(
                            name="cost_fp",
                            label="False positive cost",
                            kind="float",
                            default=1.0,
                            constraint=ParameterConstraint(min_value=0.0),
                            help_text="Cost of a false positive (used with cost_minimize objective).",
                        ),
                        ParameterDefinition(
                            name="cost_fn",
                            label="False negative cost",
                            kind="float",
                            default=10.0,
                            constraint=ParameterConstraint(min_value=0.0),
                            help_text="Cost of a false negative (used with cost_minimize objective).",
                        ),
                    ],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        objective = params.get("objective", "youden")
        if objective not in self.OBJECTIVES:
            errors.append(f"objective must be one of {sorted(self.OBJECTIVES)}, got {objective!r}")

        n_thresholds = params.get("n_thresholds", 200)
        try:
            if int(n_thresholds) < 10:
                errors.append("n_thresholds must be >= 10")
        except (ValueError, TypeError):
            errors.append("n_thresholds must be an integer")

        cost_fp = params.get("cost_fp")
        cost_fn = params.get("cost_fn")
        if objective == "cost_minimize":
            if cost_fp is None or cost_fn is None:
                errors.append("cost_fp and cost_fn are required for cost_minimize objective")
            else:
                try:
                    float(cost_fp)
                    float(cost_fn)
                except (ValueError, TypeError):
                    errors.append("cost_fp and cost_fn must be numbers")

        return errors

    def run(self, context: NodeContext) -> NodeResult:
        params = context.params
        objective = params.get("objective", "youden")
        n_thresholds = int(params.get("n_thresholds", 200))
        cost_fp = float(params.get("cost_fp", 1.0))
        cost_fn = float(params.get("cost_fn", 10.0))

        meta = context.inputs.target_metadata()
        target_col = meta.target_column if meta is not None else ""
        bad = meta.bad_values if meta is not None else frozenset()
        bad_list = list(bad)

        train_arts = context.inputs.by_role("train")
        test_arts = context.inputs.by_role("test")
        oot_arts = context.inputs.by_role("oot")
        data_arts = train_arts + test_arts + oot_arts

        report: JsonDict = {"objective": objective, "cost_fp": cost_fp, "cost_fn": cost_fn, "roles": {}}

        for data_art in data_arts:
            role = data_art.role
            df = context.inputs.read_dataframe(data_art)

            if "predicted_bad_probability" not in df.columns:
                report["roles"][role] = {"error": "Missing predicted_bad_probability"}
                continue

            y_prob = df["predicted_bad_probability"].to_numpy()
            if target_col and target_col in df.columns and bad:
                y_bin = df[target_col].cast(pl.String).is_in(bad_list).cast(pl.Int64).to_numpy()
            else:
                y_bin = np.zeros(df.height, dtype=np.int64)

            n_bad = int(y_bin.sum())
            n_good = len(y_bin) - n_bad
            if n_bad == 0 or n_good == 0:
                report["roles"][role] = {"error": "Single class; threshold optimization skipped"}
                continue

            thresholds = np.linspace(0.0, 1.0, n_thresholds)
            y_pred_matrix = (y_prob[:, None] >= thresholds[None, :]).astype(int)
            tp = np.sum((y_bin[:, None] == 1) & (y_pred_matrix == 1), axis=0)
            tn = np.sum((y_bin[:, None] == 0) & (y_pred_matrix == 0), axis=0)
            fp = np.sum((y_bin[:, None] == 0) & (y_pred_matrix == 1), axis=0)
            fn = np.sum((y_bin[:, None] == 1) & (y_pred_matrix == 0), axis=0)

            denom_tp_fn = tp + fn
            denom_tn_fp = tn + fp
            recall = np.divide(tp, denom_tp_fn, where=denom_tp_fn > 0, out=np.zeros_like(tp, dtype=float))
            specificity = np.divide(tn, denom_tn_fp, where=denom_tn_fp > 0, out=np.zeros_like(tn, dtype=float))
            precision = np.divide(tp, tp + fp, where=(tp + fp) > 0, out=np.zeros_like(tp, dtype=float))
            denom_f1 = precision + recall
            f1 = np.divide(2 * precision * recall, denom_f1, where=denom_f1 > 0, out=np.zeros_like(precision, dtype=float))
            g_mean = np.sqrt(recall * specificity)
            cost = cost_fp * fp + cost_fn * fn
            j = recall + specificity - 1.0

            if objective == "youden":
                scores = j
            elif objective == "max_f1":
                scores = f1
            elif objective == "max_g_mean":
                scores = g_mean
            elif objective == "cost_minimize":
                scores = -cost.astype(float)
            else:
                scores = np.zeros(n_thresholds)

            best_idx = int(np.argmax(scores))
            best = {
                "threshold": round(float(thresholds[best_idx]), 6),
                "objective_value": round(float(scores[best_idx]), 6),
                "detail": {
                    "recall": round(float(recall[best_idx]), 6),
                    "specificity": round(float(specificity[best_idx]), 6),
                    "precision": round(float(precision[best_idx]), 6),
                    "f1": round(float(f1[best_idx]), 6),
                    "g_mean": round(float(g_mean[best_idx]), 6),
                    "cost": round(float(cost[best_idx]), 6),
                    "youden_j": round(float(j[best_idx]), 6),
                },
            }

            report["roles"][role] = best

        selected_threshold = 0.5
        for role_priority in ["test", "train", "oot"]:
            role_data = report["roles"].get(role_priority, {})
            if "threshold" in role_data:
                selected_threshold = role_data["threshold"]
                break

        report["selected_threshold"] = selected_threshold

        context.outputs.publish_json(
            role="report",             kind=EvidenceKind.VALIDATION_EVIDENCE,
            payload=report,
            metadata={"objective": objective, "selected_threshold": selected_threshold},
        )

        context.outputs.add_metric("selected_threshold", selected_threshold)
        return context.outputs.build_result()


__definition__ = NodeDefinition(
    node_type=ThresholdOptimizationNode.node_type,
    version=ThresholdOptimizationNode.version,
    category=ThresholdOptimizationNode.category,
    description="Optimize probability threshold for binary classification decisions",
    input_contract=ArtifactContract(
        roles=tuple(ArtifactRoleSpec(r, required=True) for r in ThresholdOptimizationNode.input_roles),
    ),
    output_contract=ArtifactContract(
        roles=tuple(ArtifactRoleSpec(r, required=True) for r in ThresholdOptimizationNode.output_roles),
    ),
    parameter_schema=None,
    optional_dependencies=(),
    tier="launch",
)
