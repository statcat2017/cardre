from __future__ import annotations

from typing import Any

from cardre.nodes.parameters import (
    MethodOption,
    NodeParameterSchema,
    ParameterConstraint,
    ParameterDefinition,
)


def automatic_binning_parameter_schema(node_type: str, node_version: str) -> NodeParameterSchema:
    return NodeParameterSchema(
        node_type=node_type,
        node_version=node_version,
        title="Automatic Binning",
        default_method="fine_classing",
        methods=[
            MethodOption(
                id="fine_classing",
                label="Fine classing",
                status="available",
                description="Equal-frequency binning with optional missing handling.",
                params=[
                    ParameterDefinition(
                        name="max_bins", label="Max bins",
                        kind="integer", default=20,
                        constraint=ParameterConstraint(min_value=2),
                        help_text="Maximum number of bins per numeric variable.",
                    ),
                    ParameterDefinition(
                        name="min_bin_fraction", label="Min bin fraction",
                        kind="float", default=0.05,
                        constraint=ParameterConstraint(exclusive_min=0, exclusive_max=1),
                        help_text="Minimum fraction of rows a bin must contain.",
                    ),
                    ParameterDefinition(
                        name="missing_policy", label="Missing policy",
                        kind="string", default="separate_bin",
                        constraint=ParameterConstraint(enum_values=["separate_bin", "ignore"]),
                        help_text="How to treat missing values.",
                    ),
                    ParameterDefinition(
                        name="max_categorical_levels", label="Max categorical levels",
                        kind="integer", default=50,
                        constraint=ParameterConstraint(min_value=1),
                        help_text="Maximum levels per categorical variable.",
                    ),
                    ParameterDefinition(
                        name="exclude_columns", label="Exclude columns",
                        kind="list", default=[],
                        help_text="Column names to exclude from binning.",
                    ),
                ],
            ),
        ],
    )


def validate_automatic_binning_params(params: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_fine_classing(params))
    return errors


def _validate_fine_classing(params: dict[str, Any]) -> list[str]:
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
