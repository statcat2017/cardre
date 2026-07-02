"""BinningNode — canonical binning node supporting multiple methods.

Phase 2B unification: replaces ``cardre.fine_classing`` and
``cardre.auto_binning_fit`` with ``cardre.binning`` that dispatches
by ``params["method"]``.
"""

from __future__ import annotations

from typing import Any

from cardre.execution.context import ExecutionContext, NodeOutput
from cardre.nodes.contracts import NodeType
from cardre.node_parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


class BinningNode(NodeType):
    """Canonical binning node supporting Fine Classing and OptBinning.

    Dispatches to the appropriate implementation based on
    ``params["method"]``.
    """

    node_type = "cardre.binning"
    version = "1"
    category = "fit"
    input_roles: list[str] = ["train", "definition"]
    output_roles: list[str] = ["definition", "report"]

    # Legacy type → method mapping for read-time migration
    LEGACY_METHOD_MAP = {
        "cardre.fine_classing": "fine_classing",
        "cardre.auto_binning_fit": "optbinning",
    }
    VALID_METHODS = {"fine_classing", "optbinning"}

    @classmethod
    def parameter_schema(cls) -> NodeParameterSchema:
        return NodeParameterSchema(
            node_type=cls.node_type,
            node_version=cls.version,
            title="Binning",
            default_method="fine_classing",
            methods=[
                MethodOption(
                    id="fine_classing",
                    label="Fine classing",
                    status="available",
                    description="Equal-frequency binning with optional missing handling.",
                    params=[
                        ParameterDefinition(
                            name="method",
                            label="Method",
                            kind="string",
                            default="fine_classing",
                        ),
                        ParameterDefinition(
                            name="max_bins",
                            label="Max bins",
                            kind="integer",
                            default=20,
                            constraint=ParameterConstraint(min_value=2),
                            help_text="Maximum number of bins per numeric variable.",
                        ),
                        ParameterDefinition(
                            name="min_bin_fraction",
                            label="Min bin fraction",
                            kind="float",
                            default=0.05,
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Minimum fraction of rows a bin must contain.",
                        ),
                        ParameterDefinition(
                            name="missing_policy",
                            label="Missing policy",
                            kind="string",
                            default="separate_bin",
                            constraint=ParameterConstraint(enum_values=["separate_bin", "ignore"]),
                            help_text="How to treat missing values.",
                        ),
                        ParameterDefinition(
                            name="max_categorical_levels",
                            label="Max categorical levels",
                            kind="integer",
                            default=50,
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum levels per categorical variable.",
                        ),
                        ParameterDefinition(
                            name="exclude_columns",
                            label="Exclude columns",
                            kind="list",
                            default=[],
                            help_text="Column names to exclude from binning.",
                        ),
                    ],
                ),
                MethodOption(
                    id="optbinning",
                    label="OptBinning (supervised)",
                    status="available",
                    description="Supervised optimal binning using the optbinning engine.",
                    params=[
                        ParameterDefinition(
                            name="method",
                            label="Method",
                            kind="string",
                            default="optbinning",
                        ),
                        ParameterDefinition(
                            name="engine",
                            label="Engine",
                            kind="string",
                            default="optbinning",
                            constraint=ParameterConstraint(enum_values=["optbinning"]),
                            help_text="Binning engine to use.",
                        ),
                        ParameterDefinition(
                            name="prebinning_method",
                            label="Prebinning method",
                            kind="string",
                            default="cart",
                            constraint=ParameterConstraint(enum_values=["cart"]),
                            help_text="Method for initial prebinning.",
                        ),
                        ParameterDefinition(
                            name="solver",
                            label="Solver",
                            kind="string",
                            default="cp",
                            constraint=ParameterConstraint(enum_values=["cp", "mip"]),
                            help_text="Optimization solver.",
                        ),
                        ParameterDefinition(
                            name="divergence",
                            label="Divergence",
                            kind="string",
                            default="iv",
                            constraint=ParameterConstraint(enum_values=["iv", "js", "hellinger"]),
                            help_text="Divergence measure for binning optimality.",
                        ),
                        ParameterDefinition(
                            name="monotonic_trend",
                            label="Monotonic trend",
                            kind="string",
                            default="auto",
                            constraint=ParameterConstraint(
                                enum_values=["auto", "none", "ascending", "descending"],
                            ),
                            help_text="Monotonicity constraint for WOE trend.",
                        ),
                        ParameterDefinition(
                            name="max_n_prebins",
                            label="Max N prebins",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of prebins.",
                        ),
                        ParameterDefinition(
                            name="min_prebin_size",
                            label="Min prebin size",
                            kind="float",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Minimum fraction of rows per prebin.",
                        ),
                        ParameterDefinition(
                            name="max_n_bins",
                            label="Max N bins",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Maximum number of final bins.",
                        ),
                        ParameterDefinition(
                            name="min_bin_size",
                            label="Min bin size",
                            kind="float",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Minimum fraction of rows per final bin.",
                        ),
                        ParameterDefinition(
                            name="min_bin_n_event",
                            label="Min bin N event",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Minimum event observations per bin.",
                        ),
                        ParameterDefinition(
                            name="min_bin_n_nonevent",
                            label="Min bin N nonevent",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Minimum non-event observations per bin.",
                        ),
                        ParameterDefinition(
                            name="cat_cutoff",
                            label="Category cutoff",
                            kind="float",
                            constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                            help_text="Category frequency cutoff for categorical variables.",
                        ),
                        ParameterDefinition(
                            name="time_limit",
                            label="Time limit",
                            kind="integer",
                            constraint=ParameterConstraint(min_value=1),
                            help_text="Time limit in seconds for the solver.",
                        ),
                        ParameterDefinition(
                            name="special_codes",
                            label="Special codes",
                            kind="object",
                            default={},
                            help_text="Map of variable names to special code value lists.",
                        ),
                        ParameterDefinition(
                            name="exclude_columns",
                            label="Exclude columns",
                            kind="list",
                            default=[],
                            help_text="Column names to exclude from binning.",
                        ),
                    ],
                ),
                MethodOption(
                    id="chi_merge",
                    label="Chi-merge binning",
                    status="coming_soon",
                    description="Chi-square merge binning (coming soon).",
                    params=[],
                ),
                MethodOption(
                    id="tree_binning",
                    label="Decision tree binning",
                    status="coming_soon",
                    description="Supervised binning via decision tree splits (coming soon).",
                    params=[],
                ),
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        method = params.get("method", self.VALID_METHODS)
        if method not in self.VALID_METHODS:
            errors.append(f"method must be one of {sorted(self.VALID_METHODS)}, got {method!r}")
            return errors

        if method == "fine_classing":
            errors.extend(self._validate_fine_classing(params))
        elif method == "optbinning":
            errors.extend(self._validate_optbinning(params))
        return errors

    def _validate_fine_classing(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        max_bins = params.get("max_bins", 20)
        try:
            if int(max_bins) < 2:
                errors.append("max_bins must be >= 2")
        except (ValueError, TypeError):
            errors.append("max_bins must be an integer")
        min_bin_fraction = params.get("min_bin_fraction", 0.05)
        try:
            if not (0 < float(min_bin_fraction) < 1):
                errors.append("min_bin_fraction must be between 0 and 1")
        except (ValueError, TypeError):
            errors.append("min_bin_fraction must be a number")
        missing_policy = params.get("missing_policy", "separate_bin")
        if missing_policy not in ("separate_bin", "ignore"):
            errors.append("missing_policy must be one of: separate_bin, ignore")
        max_cat = params.get("max_categorical_levels", 50)
        try:
            if int(max_cat) < 1:
                errors.append("max_categorical_levels must be >= 1")
        except (ValueError, TypeError):
            errors.append("max_categorical_levels must be an integer")
        return errors

    def _validate_optbinning(self, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        engine = params.get("engine", "optbinning")
        if engine not in {"optbinning"}:
            return [f"engine must be one of {{'optbinning'}}, got {engine!r}"]
        if engine == "optbinning":
            try:
                import optbinning  # noqa: F401
            except ImportError:
                errors.append(
                    "optbinning package not installed. "
                    "Install with: pip install cardre[optimal-binning]"
                )

        pbm = params.get("prebinning_method", "cart")
        if pbm not in {"cart"}:
            errors.append("prebinning_method must be 'cart'")

        solver = params.get("solver", "cp")
        if solver not in {"cp", "mip"}:
            errors.append("solver must be one of {'cp', 'mip'}")

        divergence = params.get("divergence", "iv")
        if divergence not in {"iv", "js", "hellinger"}:
            errors.append("divergence must be one of {'iv', 'js', 'hellinger'}")

        trend = params.get("monotonic_trend", "auto")
        if trend not in {"auto", "none", "ascending", "descending"}:
            errors.append("monotonic_trend must be one of auto/none/ascending/descending")

        for key in ("max_n_prebins", "max_n_bins", "min_bin_n_event",
                     "min_bin_n_nonevent", "time_limit"):
            v = params.get(key)
            if v is not None:
                try:
                    if int(v) < 1:
                        errors.append(f"{key} must be >= 1")
                except (ValueError, TypeError):
                    errors.append(f"{key} must be an integer")

        for key in ("min_prebin_size", "min_bin_size", "cat_cutoff"):
            v = params.get(key)
            if v is not None:
                try:
                    fv = float(v)
                    if not (0 < fv < 1):
                        errors.append(f"{key} must be between 0 and 1")
                except (ValueError, TypeError):
                    errors.append(f"{key} must be a number")

        return errors

    def run(self, context: ExecutionContext) -> NodeOutput:
        method = context.validated_params.get("method", "fine_classing")
        if method == "fine_classing":
            return self._run_fine_classing(context)
        elif method == "optbinning":
            return self._run_optbinning(context)
        raise ValueError(f"Unknown binning method: {method!r}")

    def _run_fine_classing(self, context: ExecutionContext) -> NodeOutput:
        from cardre.nodes.build.bins import FineClassingNode

        node = FineClassingNode()
        delegated_params = {k: v for k, v in context.validated_params.items() if k != "method"}
        from dataclasses import replace
        delegated_ctx = replace(context, validated_params=delegated_params)
        return node.run(delegated_ctx)

    def _run_optbinning(self, context: ExecutionContext) -> NodeOutput:
        from cardre.nodes.build.auto_binning_fit import AutoBinningFitNode

        node = AutoBinningFitNode()
        delegated_params = {k: v for k, v in context.validated_params.items() if k != "method"}
        from dataclasses import replace
        delegated_ctx = replace(context, validated_params=delegated_params)
        return node.run(delegated_ctx)


__all__ = ["BinningNode"]
