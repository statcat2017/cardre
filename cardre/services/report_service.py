"""Phase 5A — Governance report evidence model and section manifest.

Phase 5 turns the Phase 4 audit graph into a structured governance report.
This module defines the report model and reads evidence from existing
artefacts, runs, branches, comparisons, and champion assignments.

Every claim in the report must trace to a branch, run step, artefact,
metric, warning, or champion decision.  No modelling execution, no run
records, no artefact mutation, no plan version creation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRef:
    """A single evidence claim linking a report section to its source."""
    source_type: str  # "branch", "run_step", "artifact", "comparison", "champion"
    source_id: str
    claim: str


@dataclass
class ReportSection:
    """A named section of the governance report with evidence references."""
    section_id: str
    title: str
    content: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)


@dataclass
class GovernanceReport:
    """Top-level governance report container."""
    report_id: str
    project_id: str
    branch_id: str
    created_at: str
    cardre_version: str = "0.4.0"
    sections: list[ReportSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_section(self, section: ReportSection) -> None:
        self.sections.append(section)


# ---------------------------------------------------------------------------
# Section manifest
# ---------------------------------------------------------------------------

SECTION_MANIFEST: list[dict[str, str]] = [
    {"section_id": "project_header", "title": "Project Information"},
    {"section_id": "branch_summary", "title": "Selected Branch Summary"},
    {"section_id": "data_quality", "title": "Data Quality and Exclusions"},
    {"section_id": "variable_selection", "title": "Variable Selection and IV"},
    {"section_id": "binning_definition", "title": "Binning Definition"},
    {"section_id": "model_specification", "title": "Model Specification"},
    {"section_id": "score_scaling", "title": "Score Scaling"},
    {"section_id": "validation_results", "title": "Validation Results"},
    {"section_id": "cutoff_strategy", "title": "Cutoff Strategy"},
    {"section_id": "champion_rationale", "title": "Champion Rationale"},
    {"section_id": "comparison_summary", "title": "Challenger Comparison Summary"},
    {"section_id": "evidence_footprint", "title": "Evidence Footprint and Hashes"},
    {"section_id": "warnings_and_diagnostics", "title": "Warnings and Diagnostics"},
]


def create_empty_report(project_id: str, branch_id: str, report_id: str, created_at: str) -> GovernanceReport:
    """Create an empty governance report with section stubs."""
    report = GovernanceReport(
        report_id=report_id,
        project_id=project_id,
        branch_id=branch_id,
        created_at=created_at,
    )
    for entry in SECTION_MANIFEST:
        report.add_section(ReportSection(
            section_id=entry["section_id"],
            title=entry["title"],
        ))
    return report
