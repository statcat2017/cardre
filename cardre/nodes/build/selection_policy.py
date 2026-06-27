"""Cluster selection policies for variable selection.

Replaces the repeated candidate-selection loop branches in
``VariableSelectionNode.run()`` with a policy-per-cluster abstraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class _ClusterPreselect:
    """A cluster representative chosen before the main candidate loop."""
    cluster_id: str
    variable: str
    reason: str
    eligible: list[str]
    is_override: bool = False


class ClusterPolicy(Protocol):
    """Determines which variable (if any) is preselected per cluster."""

    def preselect(
        self,
        cluster_id: str,
        variables: list[str],
        eligible: list[str],
        cluster_overrides: dict[str, dict[str, str]],
        iv_map: dict[str, float],
        cluster_member_metrics: dict[tuple[str, str], dict[str, float | None]],
        seen_clusters: set[str],
    ) -> _ClusterPreselect | None:
        ...


# ---------------------------------------------------------------------------
# No cluster policy — no preselection
# ---------------------------------------------------------------------------


class NoClusterPolicy:
    """No cluster preselection. The main candidate loop treats each
    variable independently."""

    def preselect(
        self,
        cluster_id: str,
        variables: list[str],
        eligible: list[str],
        cluster_overrides: dict[str, dict[str, str]],
        iv_map: dict[str, float],
        cluster_member_metrics: dict[tuple[str, str], dict[str, float | None]],
        seen_clusters: set[str],
    ) -> _ClusterPreselect | None:
        return None


# ---------------------------------------------------------------------------
# Representative policy — one per cluster by IV or missing rate
# ---------------------------------------------------------------------------


class RepresentativePolicy:
    """Select one representative per cluster (highest IV or lowest missing
    rate), with optional manual override."""

    def __init__(self, rule: str) -> None:
        self.rule = rule

    def preselect(
        self,
        cluster_id: str,
        variables: list[str],
        eligible: list[str],
        cluster_overrides: dict[str, dict[str, str]],
        iv_map: dict[str, float],
        cluster_member_metrics: dict[tuple[str, str], dict[str, float | None]],
        seen_clusters: set[str],
    ) -> _ClusterPreselect | None:
        if not eligible:
            return None

        # Check for manual override first
        if cluster_id in cluster_overrides:
            for override_var, override_reason in cluster_overrides[cluster_id].items():
                if override_var in eligible and override_var not in seen_clusters:
                    return _ClusterPreselect(
                        cluster_id=cluster_id,
                        variable=override_var,
                        reason=f"Cluster representative override: {override_reason}",
                        eligible=eligible,
                        is_override=True,
                    )

        # Select based on rule
        if self.rule == "one_per_cluster_highest_iv":
            rep = eligible[0]  # already sorted by IV descending
            mr = None
            reason = f"highest IV ({iv_map.get(rep, 0.0):.4f}) in cluster"
        elif self.rule == "one_per_cluster_lowest_missing":
            def _missing_key(v: str) -> float:
                m = cluster_member_metrics.get((cluster_id, v), {}).get("missing_rate")
                return float("inf") if m is None else m
            rep = min(eligible, key=_missing_key)
            mr = cluster_member_metrics.get((cluster_id, rep), {}).get("missing_rate")
            reason = f"lowest missing rate ({mr:.4f}) in cluster" if mr is not None else "lowest missing rate in cluster"
        else:
            return None

        if rep in seen_clusters:
            return None

        return _ClusterPreselect(
            cluster_id=cluster_id,
            variable=rep,
            reason=reason,
            eligible=eligible,
        )


# ---------------------------------------------------------------------------
# Manual override policy — only overrides, no automatic selection
# ---------------------------------------------------------------------------


class ManualOverridePolicy:
    """Only apply manual overrides; no automatic representative selection."""

    def preselect(
        self,
        cluster_id: str,
        variables: list[str],
        eligible: list[str],
        cluster_overrides: dict[str, dict[str, str]],
        iv_map: dict[str, float],
        cluster_member_metrics: dict[tuple[str, str], dict[str, float | None]],
        seen_clusters: set[str],
    ) -> _ClusterPreselect | None:
        if cluster_id not in cluster_overrides:
            return None
        for override_var, override_reason in cluster_overrides[cluster_id].items():
            if override_var in eligible and override_var not in seen_clusters:
                return _ClusterPreselect(
                    cluster_id=cluster_id,
                    variable=override_var,
                    reason=f"Cluster representative override: {override_reason}",
                    eligible=eligible,
                    is_override=True,
                )
        return None
