import { useState } from "react";

import type { components } from "../api/schema.d";
import { theme, pageCardStyle } from "../styles";

type Step = components["schemas"]["PlanStepResponse"];
type NodeType = components["schemas"]["NodeTypeResponse"];
type NodeParameterSchema = components["schemas"]["NodeParameterSchemaResponse"];
type ParameterDefinition = components["schemas"]["ParameterDefinitionResponse"];

interface Props {
  steps: Step[];
  stepsLoading: boolean;
  nodeTypes: NodeType[];
  onSaveStep: (stepId: string, params: Record<string, unknown>) => void;
  savePending: boolean;
}

type FieldSpec = {
  param: ParameterDefinition;
};

function isBooleanKind(kind: string): boolean {
  return kind === "boolean" || kind === "bool";
}

function isListKind(kind: string): boolean {
  return kind === "list";
}

function isObjectKind(kind: string): boolean {
  return kind === "object";
}

function isNumberKind(kind: string): boolean {
  return kind === "integer" || kind === "float" || kind === "numeric";
}

function isEnumKind(kind: string): boolean {
  return kind === "enum" || kind === "categorical";
}

function toEditableValue(value: unknown, field: FieldSpec): string | boolean {
  // When a step omits a parameter, surface the schema default in the editor.
  // Explicit null stays empty so optional fields can be left blank.
  if (value === undefined) {
    value = field.param.default;
  }
  const kind = field.param.kind;
  if (isBooleanKind(kind)) {
    return value === true || value === "true" || value === 1;
  }
  if (isListKind(kind)) {
    return Array.isArray(value) ? value.join(", ") : String(value ?? "");
  }
  if (isObjectKind(kind)) {
    if (value === null || value === undefined) return "";
    return typeof value === "string" ? value : JSON.stringify(value);
  }
  if (value === null || value === undefined) return "";
  return String(value);
}

function fromEditableValue(raw: string | boolean, field: FieldSpec): unknown {
  const kind = field.param.kind;
  if (isBooleanKind(kind)) return raw === true;
  if (isEnumKind(kind) || kind === "string") return typeof raw === "string" ? raw : "";
  if (isNumberKind(kind)) {
    const text = String(raw).trim();
    if (text === "") return null;
    return kind === "integer" ? Number.parseInt(text, 10) : Number.parseFloat(text);
  }
  if (isListKind(kind)) {
    return String(raw)
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  }
  if (isObjectKind(kind)) {
    const text = String(raw).trim();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return String(raw);
}

function enumValues(field: FieldSpec): unknown[] {
  return field.param.constraint?.enum_values ?? [];
}

export function StepParamsEditor({
  steps,
  stepsLoading,
  nodeTypes,
  onSaveStep,
  savePending,
}: Props) {
  const [drafts, setDrafts] = useState<Record<string, Record<string, string | boolean>>>({});
  const [selectedMethods, setSelectedMethods] = useState<Record<string, string>>({});
  const [jsonErrors, setJsonErrors] = useState<Record<string, Record<string, string>>>({});

  if (stepsLoading) {
    return (
      <section style={{ ...pageCardStyle, padding: 18 }}>
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Step Parameters</h3>
        <div style={{ color: theme.muted }}>Loading steps...</div>
      </section>
    );
  }

  const nodeTypeMap = new Map(nodeTypes.map((nt) => [nt.node_type, nt]));

  const editableSteps = steps
    .map((step) => ({ step, schema: nodeTypeMap.get(step.node_type)?.parameter_schema }))
    .filter(
      (entry): entry is { step: Step; schema: NodeParameterSchema } =>
        !!entry.schema && entry.schema.methods !== undefined && entry.schema.methods.length > 0,
    );

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

      {editableSteps.map(({ step, schema }) => {
        const methods = schema.methods ?? [];
        const multiMethod = methods.length > 1;
        const persistedMethod =
          typeof step.params?.method === "string" ? (step.params.method as string) : undefined;
        const candidateId =
          selectedMethods[step.step_id] ??
          persistedMethod ??
          schema.default_method ??
          methods[0]?.id ??
          "";
        const method =
          methods.find((m) => m.id === candidateId) ??
          methods.find((m) => m.id === schema.default_method) ??
          methods[0];
        const selectedMethod = method?.id ?? "";
        const fields: FieldSpec[] = (method?.params ?? []).map((param) => ({ param }));
        const draft = drafts[step.step_id] ?? {};
        const current: Record<string, unknown> = { ...step.params };
        const stepJsonErrors = jsonErrors[step.step_id] ?? {};
        const hasInvalidJson = Object.keys(stepJsonErrors).length > 0;

        return (
          <div
            key={step.step_id}
            style={{ ...pageCardStyle, padding: 14, display: "grid", gap: 10 }}
          >
            <div style={{ fontWeight: 600, fontSize: 14 }}>{step.canonical_step_id}</div>

            {multiMethod && (
              <label
                style={{
                  display: "grid",
                  gridTemplateColumns: "200px 1fr",
                  gap: 8,
                  alignItems: "center",
                  fontSize: 13,
                }}
              >
                <span style={{ color: theme.muted }}>Method</span>
                <select
                  value={selectedMethod}
                  onChange={(event) =>
                    setSelectedMethods((prev) => ({
                      ...prev,
                      [step.step_id]: event.target.value,
                    }))
                  }
                  style={{ padding: 6, borderRadius: 6, border: `1px solid ${theme.border}` }}
                >
                  {methods.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label || m.id}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {fields.length === 0 ? (
              <div style={{ color: theme.muted, fontSize: 13 }}>
                No editable parameters for this step.
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {fields.map((field) => {
                  const name = field.param.name;
                  const value = name in draft ? draft[name] : toEditableValue(current[name], field);

                  if (isBooleanKind(field.param.kind)) {
                    return (
                      <label
                        key={name}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "200px 1fr",
                          gap: 8,
                          alignItems: "center",
                          fontSize: 13,
                        }}
                      >
                        <span style={{ color: theme.muted }}>
                          {field.param.label || name}
                          {field.param.help_text && (
                            <span
                              style={{ display: "block", color: theme.mutedSoft, fontSize: 12 }}
                            >
                              {field.param.help_text}
                            </span>
                          )}
                        </span>
                        <input
                          type="checkbox"
                          checked={value === true}
                          onChange={(event) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [step.step_id]: {
                                ...prev[step.step_id],
                                [name]: event.target.checked,
                              },
                            }))
                          }
                        />
                      </label>
                    );
                  }

                  const enumOptions = isEnumKind(field.param.kind) ? enumValues(field) : [];
                  const numericAttrs = isNumberKind(field.param.kind)
                    ? {
                        type: "number" as const,
                        step: field.param.kind === "integer" ? "1" : "any",
                      }
                    : { type: "text" as const, step: undefined };
                  const control = enumOptions.length ? (
                    <select
                      value={typeof value === "string" ? value : ""}
                      onChange={(event) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [step.step_id]: {
                            ...prev[step.step_id],
                            [name]: event.target.value,
                          },
                        }))
                      }
                      style={{ padding: 6, borderRadius: 6, border: `1px solid ${theme.border}` }}
                    >
                      {enumOptions.map((option) => (
                        <option key={String(option)} value={String(option)}>
                          {String(option)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={numericAttrs.type}
                      step={numericAttrs.step}
                      value={typeof value === "string" ? value : ""}
                      onChange={(event) => {
                        const text = event.target.value;
                        setDrafts((prev) => ({
                          ...prev,
                          [step.step_id]: {
                            ...prev[step.step_id],
                            [name]: text,
                          },
                        }));
                        if (isObjectKind(field.param.kind)) {
                          setJsonErrors((prev) => {
                            const stepErrors = { ...(prev[step.step_id] ?? {}) };
                            if (text.trim() === "") {
                              delete stepErrors[name];
                            } else {
                              try {
                                JSON.parse(text);
                                delete stepErrors[name];
                              } catch {
                                stepErrors[name] = "Invalid JSON.";
                              }
                            }
                            return { ...prev, [step.step_id]: stepErrors };
                          });
                        }
                      }}
                    />
                  );

                  return (
                    <label
                      key={name}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "200px 1fr",
                        gap: 8,
                        alignItems: "center",
                        fontSize: 13,
                      }}
                    >
                      <span style={{ color: theme.muted }}>
                        {field.param.label || name}
                        {field.param.help_text && (
                          <span style={{ display: "block", color: theme.mutedSoft, fontSize: 12 }}>
                            {field.param.help_text}
                          </span>
                        )}
                      </span>
                      {control}
                      {isObjectKind(field.param.kind) && stepJsonErrors[name] && (
                        <div style={{ gridColumn: "2", color: theme.redText, fontSize: 12 }}>
                          {stepJsonErrors[name]}
                        </div>
                      )}
                    </label>
                  );
                })}
              </div>
            )}

            <button
              type="button"
              onClick={() => {
                if (hasInvalidJson) {
                  return;
                }
                const merged: Record<string, unknown> = { ...step.params };
                if (multiMethod && selectedMethod) {
                  merged.method = selectedMethod;
                }
                for (const field of fields) {
                  const name = field.param.name;
                  if (name in draft) {
                    merged[name] = fromEditableValue(draft[name] as string | boolean, field);
                  }
                }
                onSaveStep(step.step_id, merged);
              }}
              disabled={savePending || hasInvalidJson}
              style={{
                justifySelf: "start",
                padding: "8px 12px",
                borderRadius: 8,
                border: 0,
                background: savePending || hasInvalidJson ? theme.mutedSoft : theme.text,
                color: "#fff",
                cursor: savePending || hasInvalidJson ? "not-allowed" : "pointer",
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
