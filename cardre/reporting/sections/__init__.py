"""Section collectors — one file per section family.

Each module defines one or more ``SectionCollector`` classes registered
in ``SECTION_COLLECTORS``.  The collector loop in ``ReportCollector``
iterates over this list and calls ``section.build(ctx)``.
"""

from __future__ import annotations

from cardre.reporting.sections.artifacts import ArtifactsSection
from cardre.reporting.sections.champion import ChampionSection
from cardre.reporting.sections.cutoff import CutoffSection
from cardre.reporting.sections.dataset_roles import DatasetRolesSection
from cardre.reporting.sections.diagnostics import (
    CalibrationSection,
    CoefficientSignSection,
    SeparationSection,
    VifSection,
)
from cardre.reporting.sections.exclusions import ExclusionSummarySection
from cardre.reporting.sections.exports import ImplementationArtifactsSection
from cardre.reporting.sections.manual_interventions import ManualInterventionsSection
from cardre.reporting.sections.model import (
    ModelLimitationsSection,
    ModellingMetadataSection,
    ModelSection,
)
from cardre.reporting.sections.pathway import PathwaySection
from cardre.reporting.sections.redundancy import RedundancyReviewSection
from cardre.reporting.sections.reproducibility import ReproducibilitySection
from cardre.reporting.sections.run_status import RunStatusSection
from cardre.reporting.sections.sample import SampleDefinitionSection
from cardre.reporting.sections.score_scaling import ScoreScalingSection
from cardre.reporting.sections.selection import VariableSelectionSection
from cardre.reporting.sections.validation import ValidationSection
from cardre.reporting.sections.woe_iv import InitialWoeIvSection, WoeIvSection
from cardre.reporting.types import SectionCollector

SECTION_COLLECTORS: list[SectionCollector] = [
    ChampionSection(),
    PathwaySection(),
    DatasetRolesSection(),
    ExclusionSummarySection(),
    SampleDefinitionSection(),
    InitialWoeIvSection(),
    WoeIvSection(),
    ModelSection(),
    ModelLimitationsSection(),
    ModellingMetadataSection(),
    CoefficientSignSection(),
    SeparationSection(),
    VifSection(),
    CalibrationSection(),
    VariableSelectionSection(),
    ScoreScalingSection(),
    ValidationSection(),
    CutoffSection(),
    ImplementationArtifactsSection(),
    ManualInterventionsSection(),
    RedundancyReviewSection(),
    RunStatusSection(),
    ReproducibilitySection(),
    ArtifactsSection(),
]
