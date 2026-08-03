import { useState } from "react";

import type { components } from "../api/schema.d";
import { theme, pageCardStyle } from "../styles";

type Step = components["schemas"]["PlanStepResponse"];

interface Props {
  steps: Step[];
  stepsLoading: boolean;
  onSaveStep: (stepId: string, params: Record<string, unknown>) => void;
  savePending: boolean;
}

type FieldSpec = { key: string; label: string; type?: "text" | "checkbox" | "comma-list" };

const EDITABLE_STEPS: Record<string, FieldSpec[]> = {
  import: [{ key: "source_path", label: "Source path" }],
  "define-metadata": [
    { key: "target_column", label: "Target column" },
    { key: "good_values", label: "Good values", type: "comma-list" },
    { key: "bad_values", label: "Bad values", type: "comma-list" },
    { key: "purpose", label: "Purpose" },
    { key: "product", label: "Product" },
    { key: "segment", label: "Segment" },
    { key: "observation_window", label: "Observation window" },
    { key: "performance_window", label: "Performance window" },
    { key: "reject_inference_position", label: "Reject-inference position" },
  ],
  "apply-exclusions": [],
  "sample-definition": [
    { key: "sample_method", label: "Sample method" },
    { key: "sample_domain", label: "Sample domain" },
    { key: "sample_description", label: "Sample description" },
  ],
  split: [{ key: "target_column", label: "Target column" }],
  "manual-binning": [
    { key: "accept_automated", label: "Accept automated bins", type: "checkbox" },
    { key: "reviewed", label: "Bin review complete", type: "checkbox" },
  ],
  "final-woe-iv": [
    { key: "smoothing_method", label: "Smoothing method", type: "text" },
    { key: "smoothing_alpha", label: "Smoothing alpha", type: "text" },
    { key: "smoothing_rationale", label: "Smoothing rationale", type: "text" },
  ],
  "validation-metrics": [
    { key: "fail_on_missing_score", label: "Fail on missing score", type: "checkbox" },
    { key: "require_test", label: "Require test set", type: "checkbox" },
    { key: "require_oot", label: "Require OOT set", type: "checkbox" },
  ],
};

function toEditableValue(
  value: unknown,
  type: "text" | "checkbox" | "comma-list" | undefined,
): string | boolean {
  if (type === "checkbox") {
    return value === true || value === "true" || value === 1;
  }
  if (type === "comma-list") {
    return Array.isArray(value) ? value.join(", ") : String(value ?? "");
  }
  return typeof value === "string" ? value : JSON.stringify(value ?? "");
}

function fromEditableValue(
  raw: string | boolean,
  type: "text" | "checkbox" | "comma-list" | undefined,
): unknown {
  if (type === "checkbox") return raw === true;
  if (type === "comma-list") {
    return String(raw)
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  }
  return typeof raw === "string" ? raw : "";
}

// final-woe-iv carries smoothing as a nested object
// ({method, alpha, rationale}); the editor flattens it into
// smoothing_method / smoothing_alpha / smoothing_rationale keys.
function smoothingParamValue(params: Record<string, unknown>, key: string): string | boolean {
  const smoothing = (params.smoothing ?? {}) as Record<string, unknown>;
  const suffix = key.replace("smoothing_", "");
  return toEditableValue(smoothing[suffix], "text");
}

function applySmoothingField(
  merged: Record<string, unknown>,
  key: string,
  value: string | boolean,
): void {
  const smoothing = { ...((merged.smoothing as Record<string, unknown> | undefined) ?? {}) };
  const suffix = key.replace("smoothing_", "");
  smoothing[suffix] = fromEditableValue(value, "text");
  if (Object.keys(smoothing).length) {
    merged.smoothing = smoothing;
  }
}

export function StepParamsEditor({ steps, stepsLoading, onSaveStep, savePending }: Props) {
  const [drafts, setDrafts] = useState<Record<string, Record<string, string | boolean>>>({});

  const editableSteps = steps.filter((step) => step.canonical_step_id in EDITABLE_STEPS);

  if (stepsLoading) {
    return (
      <section style={{ ...pageCardStyle, padding: 18 }}>
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Step Parameters</h3>
        <div style={{ color: theme.muted }}>Loading steps...</div>
      </section>
    );
  }

  if (!editableSteps.length) {
    return null;
  }

  return (
    <section style={{ ...pageCardStyle, padding: 18, display: "grid", gap: 14 }}>
      <h3 style={{ margin: 0, fontSize: 16 }}>Step Parameters</h3>
      <p style={{ margin: 0, color: theme.muted, fontSize: 13 }}>
        Edit the essential parameters of the canonical pathway. Changes apply to the draft version
        and are validated when you commit.
      </p>

      {editableSteps.map((step) => {
        const fields = EDITABLE_STEPS[step.canonical_step_id];
        const draft = drafts[step.step_id] ?? {};
        const current: Record<string, unknown> = { ...step.params };

        return (
          <div
            key={step.step_id}
            style={{ ...pageCardStyle, padding: 14, display: "grid", gap: 10 }}
          >
            <div style={{ fontWeight: 600, fontSize: 14 }}>{step.canonical_step_id}</div>
            {fields.length === 0 ? (
              <div style={{ color: theme.muted, fontSize: 13 }}>
                No editable parameters for this step.
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {fields.map((field) => {
                  const value =
                    field.key in draft
                      ? draft[field.key]
                      : field.key.startsWith("smoothing_")
                        ? smoothingParamValue(current, field.key)
                        : toEditableValue(current[field.key], field.type);
                  return (
                    <label
                      key={field.key}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "200px 1fr",
                        gap: 8,
                        alignItems: "center",
                        fontSize: 13,
                      }}
                    >
                      <span style={{ color: theme.muted }}>{field.label}</span>
                      {field.type === "checkbox" ? (
                        <input
                          type="checkbox"
                          checked={value === true}
                          onChange={(event) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [step.step_id]: {
                                ...prev[step.step_id],
                                [field.key]: event.target.checked,
                              },
                            }))
                          }
                        />
                      ) : (
                        <input
                          type="text"
                          value={typeof value === "string" ? value : ""}
                          onChange={(event) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [step.step_id]: {
                                ...prev[step.step_id],
                                [field.key]: event.target.value,
                              },
                            }))
                          }
                        />
                      )}
                    </label>
                  );
                })}
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                const merged: Record<string, unknown> = { ...step.params };
                for (const field of fields) {
                  if (field.key in draft) {
                    if (field.key.startsWith("smoothing_")) {
                      applySmoothingField(merged, field.key, draft[field.key] as string | boolean);
                    } else {
                      merged[field.key] = fromEditableValue(
                        draft[field.key] as string | boolean,
                        field.type,
                      );
                    }
                  }
                }
                onSaveStep(step.step_id, merged);
              }}
              disabled={savePending}
              style={{
                justifySelf: "start",
                padding: "8px 12px",
                borderRadius: 8,
                border: 0,
                background: savePending ? theme.mutedSoft : theme.text,
                color: "#fff",
                cursor: savePending ? "not-allowed" : "pointer",
              }}
            >
              {savePending ? "Saving..." : "Save"}
            </button>
          </div>
        );
      })}
    </section>
  );
}
