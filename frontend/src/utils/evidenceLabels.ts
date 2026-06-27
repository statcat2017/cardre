const KIND_LABELS: Record<string, string> = {
  profile: "Data Profile",
  import: "Data Import",
  "target-definition": "Target Definition",
  split: "Split Summary",
  binning: "Binning",
  "woe-iv": "WOE/IV Evidence",
  "logistic-model": "Logistic Model",
  "score-scaling": "Score Scaling",
  "validation-metrics": "Validation Metrics",
  "report-bundle": "Report Bundle",
};

export function evidenceKindLabel(kind: string | null | undefined): string {
  if (!kind) return "Evidence";
  return KIND_LABELS[kind] || kind;
}

export function evidenceStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "available":
      return "Current";
    case "stale":
      return "Stale";
    case "partial":
      return "Partial";
    case "missing":
      return "Missing";
    case "unsupported":
      return "Unsupported";
    default:
      return status || "Unknown";
  }
}
