export interface StepDisplayMetadata {
  stepId: string;
  expectedBackendPosition: number;
  displayOrder: number;
  section: string;
  label: string;
  shortDescription: string;
}

export const STEP_DISPLAY_METADATA: Record<string, StepDisplayMetadata> = {
  "import": {
    stepId: "import",
    expectedBackendPosition: 0,
    displayOrder: 0,
    section: "Project Definition",
    label: "Import Dataset",
    shortDescription: "Load and register a local dataset",
  },
  "define-metadata": {
    stepId: "define-metadata",
    expectedBackendPosition: 1,
    displayOrder: 1,
    section: "Project Definition",
    label: "Define Modelling Metadata",
    shortDescription: "Set target column, good/bad values, and population metadata",
  },
  "apply-exclusions": {
    stepId: "apply-exclusions",
    expectedBackendPosition: 2,
    displayOrder: 2,
    section: "Project Definition",
    label: "Apply Exclusions",
    shortDescription: "Filter rows based on exclusion rules",
  },
  "profile": {
    stepId: "profile",
    expectedBackendPosition: 3,
    displayOrder: 3,
    section: "Project Definition",
    label: "Profile Dataset",
    shortDescription: "Generate column-level statistics and data quality summary",
  },
  "validate-target": {
    stepId: "validate-target",
    expectedBackendPosition: 4,
    displayOrder: 4,
    section: "Project Definition",
    label: "Validate Binary Target",
    shortDescription: "Verify the target column has valid binary values",
  },
  "sample-definition": {
    stepId: "sample-definition",
    expectedBackendPosition: 5,
    displayOrder: 5,
    section: "Project Definition",
    label: "Development Sample Definition",
    shortDescription: "Define sampling method and population parameters",
  },
  "split": {
    stepId: "split",
    expectedBackendPosition: 6,
    displayOrder: 6,
    section: "Split and Preparation",
    label: "Train/Test/OOT Split",
    shortDescription: "Split data into train, test, and out-of-time samples",
  },
  "explicit-missing-outlier-treatment": {
    stepId: "explicit-missing-outlier-treatment",
    expectedBackendPosition: 7,
    displayOrder: 7,
    section: "Split and Preparation",
    label: "Explicit Missing/Outlier Treatment",
    shortDescription: "Impute missing values and cap/floor outliers",
  },
  "fine-classing": {
    stepId: "fine-classing",
    expectedBackendPosition: 8,
    displayOrder: 8,
    section: "Binning and Selection",
    label: "Automatic Fine Classing",
    shortDescription: "Generate fine bins for all variables",
  },
  "initial-woe-iv": {
    stepId: "initial-woe-iv",
    expectedBackendPosition: 9,
    displayOrder: 9,
    section: "Binning and Selection",
    label: "Initial WOE/IV Diagnostics",
    shortDescription: "Calculate WOE and IV for initial variable ranking",
  },
  "variable-clustering": {
    stepId: "variable-clustering",
    expectedBackendPosition: 10,
    displayOrder: 10,
    section: "Binning and Selection",
    label: "Variable Clustering",
    shortDescription: "Group redundant variables and suggest cluster representatives",
  },
  "variable-selection": {
    stepId: "variable-selection",
    expectedBackendPosition: 11,
    displayOrder: 11,
    section: "Binning and Selection",
    label: "Variable Selection",
    shortDescription: "Filter to the strongest candidate variables",
  },
  "manual-binning": {
    stepId: "manual-binning",
    expectedBackendPosition: 12,
    displayOrder: 12,
    section: "Binning and Selection",
    label: "Manual Bin Editing",
    shortDescription: "Refine bin boundaries for selected variables",
  },
  "final-woe-iv": {
    stepId: "final-woe-iv",
    expectedBackendPosition: 13,
    displayOrder: 13,
    section: "Binning and Selection",
    label: "Final WOE/IV Calculation",
    shortDescription: "Recalculate WOE/IV after manual bin edits",
  },
  "woe-transform-train": {
    stepId: "woe-transform-train",
    expectedBackendPosition: 14,
    displayOrder: 14,
    section: "Model Build",
    label: "WOE Transform Train",
    shortDescription: "Apply bin definitions to produce WOE-transformed training data",
  },
  "logistic-regression": {
    stepId: "logistic-regression",
    expectedBackendPosition: 15,
    displayOrder: 15,
    section: "Model Build",
    label: "Logistic Regression",
    shortDescription: "Fit logistic regression model on WOE-transformed data",
  },
  "score-scaling": {
    stepId: "score-scaling",
    expectedBackendPosition: 16,
    displayOrder: 16,
    section: "Model Build",
    label: "Score Scaling",
    shortDescription: "Convert log-odds to scorecard points",
  },
  "build-summary-report": {
    stepId: "build-summary-report",
    expectedBackendPosition: 17,
    displayOrder: 17,
    section: "Model Build",
    label: "Build Summary Report",
    shortDescription: "Generate model summary and characteristic reports",
  },
  "apply-woe": {
    stepId: "apply-woe",
    expectedBackendPosition: 18,
    displayOrder: 18,
    section: "Validation and Strategy",
    label: "Apply WOE Mapping",
    shortDescription: "Apply WOE mappings to test and OOT data",
  },
  "apply-model": {
    stepId: "apply-model",
    expectedBackendPosition: 19,
    displayOrder: 19,
    section: "Validation and Strategy",
    label: "Apply Model",
    shortDescription: "Score test and OOT data with the fitted model",
  },
  "validation-metrics": {
    stepId: "validation-metrics",
    expectedBackendPosition: 20,
    displayOrder: 20,
    section: "Validation and Strategy",
    label: "Validation Metrics by Role",
    shortDescription: "Compute AUC, Gini, KS, and calibration by sample role",
  },
  "cutoff-analysis": {
    stepId: "cutoff-analysis",
    expectedBackendPosition: 21,
    displayOrder: 21,
    section: "Validation and Strategy",
    label: "Cutoff / Strategy Analysis",
    shortDescription: "Analyse approval rate, bad rate, and capture rate at score cutoffs",
  },
  "technical-manifest-stub": {
    stepId: "technical-manifest-stub",
    expectedBackendPosition: 22,
    displayOrder: 22,
    section: "Export Evidence",
    label: "Technical Manifest Stub",
    shortDescription: "Export technical manifest and audit evidence",
  },
};

export const SECTION_ORDER = [
  "Project Definition",
  "Split and Preparation",
  "Binning and Selection",
  "Model Build",
  "Validation and Strategy",
  "Export Evidence",
];

export function getStepDisplayMetadata(stepId: string): StepDisplayMetadata | undefined {
  return STEP_DISPLAY_METADATA[stepId];
}

export function getStepsForSection(section: string): StepDisplayMetadata[] {
  return Object.values(STEP_DISPLAY_METADATA)
    .filter((m) => m.section === section)
    .sort((a, b) => a.displayOrder - b.displayOrder);
}

/** Strip branch-owned step-id suffix to recover the canonical ID.
 *
 * Branch-owned step IDs follow the pattern ``canonical_id__br_<branch_hash>``.
 * This function strips the suffix so the base can be looked up in
 * ``STEP_DISPLAY_METADATA``. If there is no ``__br_`` suffix, returns the
 * input unchanged.
 */
export function canonicalizeStepId(stepId: string): string {
  const idx = stepId.indexOf("__br_");
  if (idx !== -1) {
    return stepId.slice(0, idx);
  }
  return stepId;
}
