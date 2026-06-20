"""Bin definition lifecycle — owns the rules for creating, normalising,
validating, refining, and serialising cardre.bin_definition.v1 payloads.

This module is the single home for bin-definition invariants.  Node types
become adapters at this seam.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from cardre.audit import JsonDict
from cardre.evidence import SCHEMA_BIN_DEFINITION

# ---------------------------------------------------------------------------
# Lifecycle-owned records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleBin:
    bin_id: str
    label: str
    lower: int | float | None = None
    upper: int | float | None = None
    lower_inclusive: bool = False
    upper_inclusive: bool = False
    categories: list[str] | None = None
    is_missing_bin: bool = False
    is_special_bin: bool = False
    is_other_bin: bool = False
    row_count: int = 0
    good_count: int = 0
    bad_count: int = 0
    bad_rate: float | None = None
    woe: float | None = None
    iv: float | None = None
    row_pct: float | None = None
    kind: str = ""
    special_values: list[Any] | None = None

    @staticmethod
    def from_dict(data: JsonDict) -> LifecycleBin:
        return LifecycleBin(
            bin_id=data.get("bin_id", ""),
            label=data.get("label", ""),
            lower=data.get("lower"),
            upper=data.get("upper"),
            lower_inclusive=bool(data.get("lower_inclusive", False)),
            upper_inclusive=bool(data.get("upper_inclusive", False)),
            categories=data.get("categories"),
            is_missing_bin=bool(data.get("is_missing_bin", False)),
            is_special_bin=bool(data.get("is_special_bin", False)),
            is_other_bin=bool(data.get("is_other_bin", False)),
            row_count=int(data.get("row_count", 0)),
            good_count=int(data.get("good_count", 0)),
            bad_count=int(data.get("bad_count", 0)),
            bad_rate=data.get("bad_rate"),
            woe=data.get("woe"),
            iv=data.get("iv"),
            row_pct=data.get("row_pct"),
            kind=data.get("kind", ""),
            special_values=data.get("special_values"),
        )

    def to_dict(self) -> JsonDict:
        d: JsonDict = {
            "bin_id": self.bin_id,
            "label": self.label,
            "lower": self.lower,
            "upper": self.upper,
            "lower_inclusive": self.lower_inclusive,
            "upper_inclusive": self.upper_inclusive,
            "categories": self.categories,
            "is_missing_bin": self.is_missing_bin,
            "row_count": self.row_count,
            "good_count": self.good_count,
            "bad_count": self.bad_count,
        }
        if self.is_special_bin:
            d["is_special_bin"] = True
        if self.is_other_bin:
            d["is_other_bin"] = True
        if self.kind:
            d["kind"] = self.kind
        if self.bad_rate is not None:
            d["bad_rate"] = self.bad_rate
        if self.woe is not None:
            d["woe"] = self.woe
        if self.iv is not None:
            d["iv"] = self.iv
        if self.row_pct is not None:
            d["row_pct"] = self.row_pct
        if self.special_values is not None:
            d["special_values"] = self.special_values
        return d


@dataclass(frozen=True)
class LifecycleVariable:
    variable: str
    kind: str = ""
    dtype: str = ""
    bins: list[LifecycleBin] = field(default_factory=list)
    status: str = ""
    active: bool = True
    metrics: JsonDict = field(default_factory=dict)
    warnings: list[JsonDict] = field(default_factory=list)
    override_history: list[JsonDict] = field(default_factory=list)
    failure_reason: str | None = None

    @staticmethod
    def from_dict(data: JsonDict) -> LifecycleVariable:
        return LifecycleVariable(
            variable=data.get("variable", ""),
            kind=data.get("kind", ""),
            dtype=data.get("dtype", ""),
            bins=[LifecycleBin.from_dict(b) for b in data.get("bins", [])],
            status=data.get("status", ""),
            active=bool(data.get("active", True)),
            metrics=dict(data.get("metrics", {})),
            warnings=list(data.get("warnings", [])),
            override_history=list(data.get("override_history", [])),
            failure_reason=data.get("failure_reason"),
        )

    def to_dict(self) -> JsonDict:
        d: JsonDict = {
            "variable": self.variable,
            "kind": self.kind,
            "bins": [b.to_dict() for b in self.bins],
            "active": self.active,
        }
        if self.dtype:
            d["dtype"] = self.dtype
        if self.status:
            d["status"] = self.status
        if self.metrics:
            d["metrics"] = self.metrics
        if self.warnings:
            d["warnings"] = self.warnings
        if self.override_history:
            d["override_history"] = self.override_history
        if self.failure_reason:
            d["failure_reason"] = self.failure_reason
        return d


@dataclass(frozen=True)
class LifecycleBinDefinition:
    schema_version: str = SCHEMA_BIN_DEFINITION
    variables: list[LifecycleVariable] = field(default_factory=list)
    rejected: list[LifecycleVariable] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    source: JsonDict | None = None

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    @classmethod
    def from_payload(cls, payload: JsonDict) -> LifecycleBinDefinition:
        def _parse_variable_list(raw: list) -> list[LifecycleVariable]:
            return [LifecycleVariable.from_dict(v) for v in raw]

        rejected_raw = payload.get("rejected", []) or []
        return cls(
            schema_version=payload.get("schema_version", SCHEMA_BIN_DEFINITION),
            variables=_parse_variable_list(payload.get("variables", [])),
            rejected=_parse_variable_list(rejected_raw),
            warnings=list(payload.get("warnings", [])),
            source=copy.deepcopy(payload.get("source")) if "source" in payload else None,
        )

    @classmethod
    def from_variables(
        cls,
        variables: list[LifecycleVariable],
        rejected: list[LifecycleVariable] | None = None,
        warnings: list[JsonDict] | None = None,
        source: JsonDict | None = None,
    ) -> LifecycleBinDefinition:
        return cls(
            variables=variables,
            rejected=rejected or [],
            warnings=warnings or [],
            source=source,
        )

    # ------------------------------------------------------------------
    # Serialize
    # ------------------------------------------------------------------

    def to_payload(self) -> JsonDict:
        payload: JsonDict = {
            "schema_version": self.schema_version,
            "variables": [v.to_dict() for v in self.variables],
            "warnings": list(self.warnings),
            "rejected": [r.to_dict() for r in self.rejected],
        }
        if self.source is not None:
            payload["source"] = copy.deepcopy(self.source)
        return payload

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    def normalize(self) -> LifecycleBinDefinition:
        return LifecycleBinDefinition(
            schema_version=SCHEMA_BIN_DEFINITION,
            variables=[self._normalize_var(v) for v in self.variables],
            rejected=[self._normalize_var(r) for r in self.rejected],
            warnings=list(self.warnings),
            source=copy.deepcopy(self.source) if self.source is not None else None,
        )

    @staticmethod
    def _normalize_var(var: LifecycleVariable) -> LifecycleVariable:
        normalized_bins = []
        for b in var.bins:
            nb = LifecycleBin(
                bin_id=b.bin_id,
                label=b.label,
                lower=b.lower,
                upper=b.upper,
                lower_inclusive=b.lower_inclusive,
                upper_inclusive=b.upper_inclusive,
                categories=b.categories,
                is_missing_bin=b.is_missing_bin,
                is_special_bin=b.is_special_bin,
                is_other_bin=b.is_other_bin,
                row_count=b.row_count,
                good_count=b.good_count,
                bad_count=b.bad_count,
                bad_rate=b.bad_rate,
                woe=b.woe,
                iv=b.iv,
                row_pct=b.row_pct,
                kind=b.kind,
                special_values=b.special_values,
            )
            normalized_bins.append(nb)
        return LifecycleVariable(
            variable=var.variable,
            kind=var.kind,
            dtype=var.dtype,
            bins=normalized_bins,
            status=var.status,
            active=var.active,
            metrics={k: v for k, v in var.metrics.items()},
            warnings=list(var.warnings),
            override_history=list(var.override_history),
            failure_reason=var.failure_reason,
        )

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        errors: list[str] = []

        if not self.schema_version:
            errors.append("schema_version is required")

        var_names: set[str] = set()
        for v in self.variables:
            if v.variable in var_names:
                errors.append(f"Duplicate variable in active list: {v.variable!r}")
            var_names.add(v.variable)

            bid_set: set[str] = set()
            for b in v.bins:
                if b.bin_id in bid_set:
                    errors.append(f"Duplicate bin_id {b.bin_id!r} in variable {v.variable!r}")
                bid_set.add(b.bin_id)

        rej_names: set[str] = set()
        for r in self.rejected:
            if r.variable in rej_names:
                errors.append(f"Duplicate variable in rejected list: {r.variable!r}")
            rej_names.add(r.variable)

        overlap = var_names & rej_names
        if overlap:
            errors.append(f"Variable(s) appear in both active and rejected lists: {sorted(overlap)}")

        return errors

    # ------------------------------------------------------------------
    # Override validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_overrides(
        bin_def: JsonDict,
        overrides: list[JsonDict],
        selected_vars: set[str] | None = None,
    ) -> list[str]:
        errors: list[str] = []
        var_map = {v["variable"]: v for v in bin_def.get("variables", [])}

        for i, override in enumerate(overrides):
            prefix = f"overrides[{i}]"
            variable = override.get("variable", "")
            action = override.get("action", "")
            reason = override.get("reason", "")
            source_bin_ids = override.get("source_bin_ids", [])

            if not reason:
                errors.append(f"{prefix}: override for '{variable}' requires a non-empty reason")
                continue
            if variable not in var_map:
                errors.append(f"{prefix}: references unknown variable '{variable}'")
                continue
            if selected_vars is not None and variable not in selected_vars:
                errors.append(
                    f"{prefix}: variable '{variable}' was not selected by variable-selection "
                    f"and cannot accept manual binning overrides"
                )
                continue
            VALID = ("merge_bins", "group_categories",
                      "reject_variable", "reorder_missing_bin", "reorder_special_bin")
            if action not in VALID:
                errors.append(f"{prefix}: unsupported action '{action}'")
                continue

            var_bins = var_map[variable].get("bins", [])
            bin_id_map = {b["bin_id"]: b for b in var_bins}

            for bid in source_bin_ids:
                if bid not in bin_id_map:
                    errors.append(f"{prefix}: bin_id '{bid}' not found in variable '{variable}'")

            if errors:
                continue

            if action == "merge_bins":
                if len(source_bin_ids) < 2:
                    errors.append(f"{prefix}: merge_bins requires at least 2 source bins")
                    continue
                kind = var_map[variable].get("kind", "")
                if kind == "numeric":
                    bin_positions = [var_bins.index(bin_id_map[bid]) for bid in source_bin_ids]
                    expected_positions = list(range(min(bin_positions), max(bin_positions) + 1))
                    if bin_positions != expected_positions:
                        errors.append(
                            f"{prefix}: numeric bin merge requires adjacent bins. "
                            f"Source bins at positions {bin_positions} are not contiguous."
                        )

        return errors

    # ------------------------------------------------------------------
    # Override application
    # ------------------------------------------------------------------

    @staticmethod
    def apply_overrides(
        bin_def: JsonDict,
        overrides: list[JsonDict],
        selected_vars: set[str] | None = None,
    ) -> JsonDict:
        var_map = {v["variable"]: dict(v) for v in bin_def.get("variables", [])}
        warnings: list[JsonDict] = []

        for override in overrides:
            variable = override.get("variable", "")
            action = override.get("action", "")
            source_bin_ids = override.get("source_bin_ids", [])
            reason = override.get("reason", "")

            if variable not in var_map:
                raise ValueError(f"Override references unknown variable '{variable}'")

            var_info = var_map[variable]
            var_bins = list(var_info.get("bins", []))
            bin_id_map = {b["bin_id"]: b for b in var_bins}

            override_event = {
                "user_action": action,
                "variable": variable,
                "reason": reason,
                "source_bin_ids": source_bin_ids,
            }
            override_history = (
                list(var_info.get("override_history", []))
                if isinstance(var_info.get("override_history"), list) else []
            )

            if action == "merge_bins":
                before_labels = [bin_id_map[bid].get("label", bid) for bid in source_bin_ids]
                merged = {
                    "bin_id": f"{variable}_manual_{override.get('new_label', 'merged').lower().replace(' ', '_')}",
                    "label": override.get("new_label", "Merged"),
                    "lower": bin_id_map[source_bin_ids[0]].get("lower"),
                    "upper": bin_id_map[source_bin_ids[-1]].get("upper"),
                    "lower_inclusive": bin_id_map[source_bin_ids[0]].get("lower_inclusive", False),
                    "upper_inclusive": bin_id_map[source_bin_ids[-1]].get("upper_inclusive", True),
                    "categories": None,
                    "is_missing_bin": False,
                    "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                    "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                    "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
                }
                override_event["before"] = before_labels
                override_event["after"] = merged["label"]
                new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
                insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
                new_bins.insert(insert_pos, merged)
                var_info["bins"] = new_bins

            elif action == "group_categories":
                before_cats = []
                for bid in source_bin_ids:
                    before_cats.extend(bin_id_map[bid].get("categories", []))
                grouped = {
                    "bin_id": f"{variable}_manual_grouped",
                    "label": override.get("new_label", "Grouped"),
                    "lower": None, "upper": None,
                    "lower_inclusive": False, "upper_inclusive": False,
                    "categories": before_cats,
                    "is_missing_bin": False,
                    "row_count": sum(bin_id_map[bid].get("row_count", 0) for bid in source_bin_ids),
                    "good_count": sum(bin_id_map[bid].get("good_count", 0) for bid in source_bin_ids),
                    "bad_count": sum(bin_id_map[bid].get("bad_count", 0) for bid in source_bin_ids),
                }
                override_event["before"] = before_cats
                override_event["after"] = override.get("new_label", "Grouped")
                new_bins = [b for b in var_bins if b["bin_id"] not in source_bin_ids]
                insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
                new_bins.insert(insert_pos, grouped)
                var_info["bins"] = new_bins

            elif action == "reject_variable":
                override_event["before"] = "included"
                override_event["after"] = "excluded"
                var_info["status"] = "excluded"
                var_info["active"] = False
                var_info["reject_reason"] = reason

            elif action == "reorder_missing_bin":
                missing_bins = [b for b in var_bins if b.get("is_missing_bin")]
                non_missing = [b for b in var_bins if not b.get("is_missing_bin")]
                var_info["bins"] = non_missing + missing_bins
                override_event["before"] = "missing_at_original_position"
                override_event["after"] = "missing_moved_to_end"

            elif action == "reorder_special_bin":
                special_bins = [b for b in var_bins if b.get("is_special_bin")]
                non_special = [b for b in var_bins if not b.get("is_special_bin")]
                var_info["bins"] = non_special + special_bins
                override_event["before"] = "special_at_original_position"
                override_event["after"] = "special_moved_to_end"

            override_history.append(override_event)
            var_info["override_history"] = override_history

        if selected_vars is not None:
            var_map = {k: v for k, v in var_map.items() if k in selected_vars}

        active_vars = [v for v in var_map.values() if v.get("active", True)]
        rejected_vars = [v for v in var_map.values() if not v.get("active", True)]

        existing_rejected = list(bin_def.get("rejected") or [])
        combined_rejected = existing_rejected + rejected_vars

        if not overrides:
            warnings.append({"message": "No manual overrides applied; passing through auto bins for selected variables"})

        return {
            "variables": active_vars,
            "rejected": combined_rejected if combined_rejected else None,
            "warnings": bin_def.get("warnings", []) + warnings,
        }
