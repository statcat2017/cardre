"""Bin definition lifecycle — owns the rules for creating, normalising,
validating, refining, and serialising cardre.bin_definition.v1 payloads.

This module is the single home for bin-definition invariants.  Node types
become adapters at this seam.
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field
from typing import Any

from cardre.domain.diagnostics import JsonDict

# Schema constant lives here, re-exported from evidence.py for backward
# compatibility.  The lifecycle module is the deeper domain module;
# evidence depends on it, not the other way around.
SCHEMA_BIN_DEFINITION = "cardre.bin_definition.v1"

# Which fields are always emitted vs tracked for presence preservation
_VAR_ALWAYS: frozenset[str] = frozenset({"variable", "kind", "bins"})
_DEF_ALWAYS: frozenset[str] = frozenset({"schema_version", "variables"})

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
    extra: JsonDict = field(default_factory=dict)

    _BIN_KNOWN: frozenset[str] = frozenset({
        "bin_id", "label", "lower", "upper", "lower_inclusive",
        "upper_inclusive", "categories", "is_missing_bin", "is_special_bin",
        "is_other_bin", "row_count", "good_count", "bad_count", "bad_rate",
        "woe", "iv", "row_pct", "kind", "special_values",
    })

    @staticmethod
    def from_dict(data: JsonDict) -> LifecycleBin:
        known = LifecycleBin._BIN_KNOWN
        extra = {k: v for k, v in data.items() if k not in known}
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
            extra=extra,
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
        d.update(self.extra)
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
    extra: JsonDict = field(default_factory=dict)

    # Optional fields whose presence in the source payload should be
    # tracked so to_dict() reproduces the original shape.
    _present_fields: frozenset[str] | None = field(default=None, repr=False)

    _VAR_OPTIONAL: frozenset[str] = frozenset({
        "active", "dtype", "status", "metrics", "warnings",
        "override_history", "failure_reason",
    })

    @staticmethod
    def from_dict(data: JsonDict) -> LifecycleVariable:
        known = _VAR_ALWAYS | LifecycleVariable._VAR_OPTIONAL
        extra = {k: v for k, v in data.items() if k not in known}
        present = frozenset(k for k in data if k in LifecycleVariable._VAR_OPTIONAL)
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
            extra=extra,
            _present_fields=present,
        )

    def to_dict(self) -> JsonDict:
        d: JsonDict = {
            "variable": self.variable,
            "kind": self.kind,
            "bins": [b.to_dict() for b in self.bins],
        }
        present = self._present_fields
        if present is None or "active" in present:
            d["active"] = self.active
        if (present is None or "dtype" in present) and self.dtype:
            d["dtype"] = self.dtype
        if (present is None or "status" in present) and self.status:
            d["status"] = self.status
        if (present is None or "metrics" in present) and self.metrics:
            d["metrics"] = self.metrics
        if (present is None or "warnings" in present) and self.warnings:
            d["warnings"] = self.warnings
        if (present is None or "override_history" in present) and self.override_history:
            d["override_history"] = self.override_history
        if (present is None or "failure_reason" in present) and self.failure_reason:
            d["failure_reason"] = self.failure_reason
        d.update(self.extra)
        return d


@dataclass(frozen=True)
class LifecycleBinDefinition:
    schema_version: str = SCHEMA_BIN_DEFINITION
    variables: list[LifecycleVariable] = field(default_factory=list)
    rejected: list[LifecycleVariable] = field(default_factory=list)
    warnings: list[JsonDict] = field(default_factory=list)
    source: JsonDict | None = None
    extra: JsonDict = field(default_factory=dict)

    _DEF_OPTIONAL: frozenset[str] = frozenset({
        "rejected", "warnings", "source",
    })

    _present_fields: frozenset[str] | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    @classmethod
    def from_payload(cls, payload: JsonDict) -> LifecycleBinDefinition:
        def _parse_variable_list(raw: list[Any]) -> list[LifecycleVariable]:
            return [LifecycleVariable.from_dict(v) for v in raw]

        rejected_raw = payload.get("rejected", []) or []
        known = _DEF_ALWAYS | cls._DEF_OPTIONAL
        extra = {k: v for k, v in payload.items() if k not in known}
        present = frozenset(k for k in payload if k in cls._DEF_OPTIONAL)
        return cls(
            schema_version=payload.get("schema_version", SCHEMA_BIN_DEFINITION),
            variables=_parse_variable_list(payload.get("variables", [])),
            rejected=_parse_variable_list(rejected_raw),
            warnings=list(payload.get("warnings", [])),
            source=copy.deepcopy(payload.get("source")) if "source" in payload else None,
            extra=extra,
            _present_fields=present,
        )

    @classmethod
    def from_variables(
        cls,
        variables: list[LifecycleVariable],
        rejected: list[LifecycleVariable] | None = None,
        warnings: list[JsonDict] | None = None,
        source: JsonDict | None = None,
    ) -> LifecycleBinDefinition:
        present: set[str] = set()
        if rejected is not None:
            present.add("rejected")
        if warnings is not None:
            present.add("warnings")
        if source is not None:
            present.add("source")
        return cls(
            variables=variables,
            rejected=rejected or [],
            warnings=warnings or [],
            source=source,
            _present_fields=frozenset(present) if present else None,
        )

    # ------------------------------------------------------------------
    # Serialize
    # ------------------------------------------------------------------

    def to_payload(self) -> JsonDict:
        present = self._present_fields
        payload: JsonDict = {
            "schema_version": self.schema_version,
            "variables": [v.to_dict() for v in self.variables],
        }
        if present is None or "warnings" in present:
            payload["warnings"] = list(self.warnings)
        if present is None or "rejected" in present:
            payload["rejected"] = [r.to_dict() for r in self.rejected]
        if (present is None or "source" in present) and self.source is not None:
            payload["source"] = copy.deepcopy(self.source)
        payload.update(self.extra)
        return payload

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    def normalize(self) -> LifecycleBinDefinition:
        return dataclasses.replace(self, schema_version=SCHEMA_BIN_DEFINITION)

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
        bin_def: LifecycleBinDefinition,
        overrides: list[JsonDict],
        selected_vars: set[str] | None = None,
    ) -> list[str]:
        errors: list[str] = []
        var_map = {v.variable: v for v in bin_def.variables}

        for i, override in enumerate(overrides):
            prefix = f"overrides[{i}]"
            variable = override.get("variable", "")
            action = override.get("action", "")
            reason = override.get("reason", "")
            source_bin_ids = override.get("source_bin_ids", [])

            override_errors: list[str] = []

            if not reason:
                override_errors.append(f"{prefix}: override for '{variable}' requires a non-empty reason")
            if variable not in var_map:
                override_errors.append(f"{prefix}: references unknown variable '{variable}'")
            if selected_vars is not None and variable not in selected_vars:
                override_errors.append(
                    f"{prefix}: variable '{variable}' was not selected by variable-selection "
                    f"and cannot accept manual binning overrides"
                )
            VALID = ("merge_bins", "group_categories",
                      "reject_variable", "reorder_missing_bin", "reorder_special_bin")
            if action not in VALID:
                override_errors.append(f"{prefix}: unsupported action '{action}'")

            if override_errors:
                errors.extend(override_errors)
                continue

            var_bins = var_map[variable].bins
            bin_id_map = {b.bin_id: b for b in var_bins}

            bin_id_errors: list[str] = []
            for bid in source_bin_ids:
                if bid not in bin_id_map:
                    bin_id_errors.append(f"{prefix}: bin_id '{bid}' not found in variable '{variable}'")
            if bin_id_errors:
                errors.extend(bin_id_errors)
                continue

            if action == "merge_bins":
                if len(source_bin_ids) < 2:
                    errors.append(f"{prefix}: merge_bins requires at least 2 source bins")
                    continue
                kind = var_map[variable].kind
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
        bin_def: LifecycleBinDefinition,
        overrides: list[JsonDict],
        selected_vars: set[str] | None = None,
    ) -> LifecycleBinDefinition:
        warnings: list[JsonDict] = []
        new_variables: list[LifecycleVariable] = []

        for var in bin_def.variables:
            var_bins = list(var.bins)
            bin_id_map = {b.bin_id: b for b in var_bins}
            override_history: list[JsonDict] = list(var.override_history)
            modified = False

            for override in overrides:
                variable = override.get("variable", "")
                action = override.get("action", "")
                source_bin_ids = override.get("source_bin_ids", [])
                reason = override.get("reason", "")

                if variable != var.variable:
                    continue

                modified = True
                override_event: JsonDict = {
                    "user_action": action,
                    "variable": variable,
                    "reason": reason,
                    "source_bin_ids": source_bin_ids,
                }

                if action == "merge_bins":
                    before_labels = [bin_id_map[bid].label for bid in source_bin_ids]
                    merged = LifecycleBin(
                        bin_id=f"{variable}_manual_{override.get('new_label', 'merged').lower().replace(' ', '_')}",
                        label=override.get("new_label", "Merged"),
                        lower=bin_id_map[source_bin_ids[0]].lower,
                        upper=bin_id_map[source_bin_ids[-1]].upper,
                        lower_inclusive=bin_id_map[source_bin_ids[0]].lower_inclusive,
                        upper_inclusive=bin_id_map[source_bin_ids[-1]].upper_inclusive,
                        categories=None,
                        is_missing_bin=False,
                        row_count=sum(bin_id_map[bid].row_count for bid in source_bin_ids),
                        good_count=sum(bin_id_map[bid].good_count for bid in source_bin_ids),
                        bad_count=sum(bin_id_map[bid].bad_count for bid in source_bin_ids),
                    )
                    override_event["before"] = before_labels
                    override_event["after"] = merged.label
                    new_bins = [b for b in var_bins if b.bin_id not in source_bin_ids]
                    insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
                    new_bins.insert(insert_pos, merged)
                    var_bins = new_bins
                    bin_id_map = {b.bin_id: b for b in var_bins}

                elif action == "group_categories":
                    before_cats: list[str] = []
                    for bid in source_bin_ids:
                        c = bin_id_map[bid].categories
                        if c:
                            before_cats.extend(c)
                    grouped = LifecycleBin(
                        bin_id=f"{variable}_manual_grouped",
                        label=override.get("new_label", "Grouped"),
                        lower=None, upper=None,
                        lower_inclusive=False, upper_inclusive=False,
                        categories=before_cats,
                        is_missing_bin=False,
                        row_count=sum(bin_id_map[bid].row_count for bid in source_bin_ids),
                        good_count=sum(bin_id_map[bid].good_count for bid in source_bin_ids),
                        bad_count=sum(bin_id_map[bid].bad_count for bid in source_bin_ids),
                    )
                    override_event["before"] = before_cats
                    override_event["after"] = override.get("new_label", "Grouped")
                    new_bins = [b for b in var_bins if b.bin_id not in source_bin_ids]
                    insert_pos = min(var_bins.index(bin_id_map[bid]) for bid in source_bin_ids)
                    new_bins.insert(insert_pos, grouped)
                    var_bins = new_bins
                    bin_id_map = {b.bin_id: b for b in var_bins}

                elif action == "reject_variable":
                    override_event["before"] = "included"
                    override_event["after"] = "excluded"

                elif action == "reorder_missing_bin":
                    missing_bins = [b for b in var_bins if b.is_missing_bin]
                    non_missing = [b for b in var_bins if not b.is_missing_bin]
                    var_bins = non_missing + missing_bins
                    bin_id_map = {b.bin_id: b for b in var_bins}
                    override_event["before"] = "missing_at_original_position"
                    override_event["after"] = "missing_moved_to_end"

                elif action == "reorder_special_bin":
                    special_bins = [b for b in var_bins if b.is_special_bin]
                    non_special = [b for b in var_bins if not b.is_special_bin]
                    var_bins = non_special + special_bins
                    bin_id_map = {b.bin_id: b for b in var_bins}
                    override_event["before"] = "special_at_original_position"
                    override_event["after"] = "special_moved_to_end"

                override_history.append(override_event)

            if modified:
                new_variables.append(dataclasses.replace(
                    var, bins=var_bins, override_history=override_history,
                ))
            else:
                new_variables.append(var)

        if selected_vars is not None:
            new_variables = [v for v in new_variables if v.variable in selected_vars]

        active_vars = [v for v in new_variables if v.active]
        rejected_vars = [v for v in new_variables if not v.active]

        combined_rejected = list(bin_def.rejected) + rejected_vars

        if not overrides:
            warnings.append({"message": "No manual overrides applied; passing through auto bins for selected variables"})

        return LifecycleBinDefinition(
            schema_version=bin_def.schema_version,
            variables=active_vars,
            rejected=combined_rejected,
            warnings=list(bin_def.warnings) + warnings,
            source=bin_def.source,
            extra=dict(bin_def.extra),
            _present_fields=bin_def._present_fields,
        )


__all__ = [
    "SCHEMA_BIN_DEFINITION",
    "LifecycleBin",
    "LifecycleBinDefinition",
    "LifecycleVariable",
]
