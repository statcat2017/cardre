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

const SCALAR_ITEM_KINDS = new Set([
  "string",
  "integer",
  "float",
  "number",
  "numeric",
  "boolean",
  "bool",
]);

/** A list whose items are structured objects, not scalar comma-separated values. */
function isStructuredList(field: FieldSpec): boolean {
  const itemKind = field.param.item_kind;
  return field.param.kind === "list" && itemKind != null && !SCALAR_ITEM_KINDS.has(itemKind);
}

/** Fields whose editable text is a JSON value (object or structured list). */
function isJsonField(field: FieldSpec): boolean {
  return isObjectKind(field.param.kind) || isStructuredList(field);
}

/** Returns a validation error string for a JSON field, or null when valid/empty. */
function jsonFieldError(text: string, field: FieldSpec): string | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return isStructuredList(field) ? "Invalid JSON array." : "Invalid JSON.";
  }
  if (isStructuredList(field) && !Array.isArray(parsed)) {
    return "Must be a JSON array.";
  }
  return null;
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
  if (isStructuredList(field)) {
    if (value === null || value === undefined) return "";
    return typeof value === "string" ? value : JSON.stringify(value);
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
  if (isEnumKind(kind) || kind === "string") {
    // String-kind enums stay strings (enum constraints are authoritative for
    // kind="string"). If a schema ever carries a numeric enum, recover the
    // original typed value rather than silently stringifying it.
    if (typeof raw === "string" && field.param.constraint?.enum_values) {
      const matched = field.param.constraint.enum_values.find((v) => String(v) === raw);
      if (matched !== undefined) return matched;
    }
    return typeof raw === "string" ? raw : "";
  }
  if (isNumberKind(kind)) {
    const text = String(raw).trim();
    if (text === "") return null;
    return kind === "integer" ? Number.parseInt(text, 10) : Number.parseFloat(text);
  }
  if (isStructuredList(field)) {
    const text = String(raw).trim();
    if (!text) {
      // Clearing a structured list falls back to the schema default when that
      // default is an array (e.g. ManualBinning overrides -> []), never null.
      // Empty optional objects still normalize to null below.
      return Array.isArray(field.param.default) ? field.param.default : null;
    }
    return JSON.parse(text);
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
    // Invalid JSON is blocked before save by the inline error gate, so a
    // successful parse is guaranteed here.
    return JSON.parse(text);
  }
  return String(raw);
}

function enumValues(field: FieldSpec): unknown[] {
  // An empty string can serve as an "unset" sentinel in enum_values, which the
  // backend rejects. Filter it out so it is never offered as a selectable
  // option while real values (including numeric strings) are preserved.
  return (field.param.constraint?.enum_values ?? []).filter(
    (value) => !(typeof value === "string" && value === ""),
  );
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
        // Only JSON fields rendered by the currently selected method can block
        // saving. Errors from a previously selected method's fields that are no
        // longer rendered must not keep Save disabled.
        const hasInvalidJson = fields.some(
          (field) => isJsonField(field) && stepJsonErrors[field.param.name] != null,
        );

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

                  const enumOptions = enumValues(field);
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
                        if (isJsonField(field)) {
                          const error = jsonFieldError(text, field);
                          setJsonErrors((prev) => {
                            const stepErrors = { ...(prev[step.step_id] ?? {}) };
                            if (error === null) {
                              delete stepErrors[name];
                            } else {
                              stepErrors[name] = error;
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
                      {isJsonField(field) && stepJsonErrors[name] && (
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
                // Re-validate every drafted JSON field directly against the
                // current draft so a stale or programmatically-populated draft
                // cannot slip invalid JSON past the onChange-populated gate.
                const freshErrors: Record<string, string> = {};
                for (const field of fields) {
                  const name = field.param.name;
                  if (isJsonField(field) && name in draft) {
                    const error = jsonFieldError(String(draft[name]), field);
                    if (error !== null) {
                      freshErrors[name] = error;
                    }
                  }
                }
                if (Object.keys(freshErrors).length > 0) {
                  setJsonErrors((prev) => ({ ...prev, [step.step_id]: freshErrors }));
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
