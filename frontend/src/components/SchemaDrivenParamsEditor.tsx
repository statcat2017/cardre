import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { UpdateStepParamsResponse } from "../types";
import { useMessage } from "../hooks/useMessage";
import { MessageBanner } from "./MessageBanner";

// --- Local types for the schema API response (backend returns `methods` but
//     auto-generated types still reflect the legacy shape) ---
interface ParamConstraint {
  min_value?: number;
  max_value?: number;
  enum_values?: unknown[];
  min_items?: number;
}

interface ParamDefinition {
  name: string;
  label: string;
  kind: string;
  default: unknown;
  required: boolean;
  constraint: ParamConstraint | null;
  help_text: string;
  group: string;
}

interface MethodDefinition {
  id: string;
  label: string;
  status: "available" | "coming_soon";
  params: ParamDefinition[];
  description: string;
}

interface SchemaResponse {
  node_type: string;
  version: string;
  title: string;
  methods: MethodDefinition[];
  params_schema: Record<string, unknown>;
  defaults: Record<string, unknown>;
  description: string;
}

interface Props {
  planId: string;
  stepId: string;
  projectId: string;
  currentParams: Record<string, unknown>;
  basePlanVersionId: string;
  nodeType: string;
  onSaved: (resp: UpdateStepParamsResponse | { latest_version_id?: string }) => void;
}

const STALE_VERSION_CODE = "STALE_VERSION";

export function SchemaDrivenParamsEditor({
  planId,
  stepId,
  projectId,
  currentParams,
  basePlanVersionId,
  nodeType,
  onSaved,
}: Props) {
  const { msg, msgType, clearMsg, setError, setInfo, setSuccess } = useMessage();

  // 1. Fetch schema
  const {
    data: schema,
    isLoading: schemaLoading,
    error: schemaError,
  } = useQuery({
    queryKey: ["nodeTypeSchema", nodeType],
    queryFn: () => api.getNodeTypeSchema(nodeType) as Promise<SchemaResponse>,
    enabled: !!nodeType,
  });

  // 2. Method selection
  const availableMethods = useMemo(
    () => (schema?.methods ?? []).filter((m) => m.status === "available"),
    [schema]
  );

  const [selectedMethodId, setSelectedMethodId] = useState<string | null>(null);

  const selectedMethod = useMemo(
    () => schema?.methods.find((m) => m.id === selectedMethodId) ?? null,
    [schema, selectedMethodId]
  );

  // Auto-select first available method on schema load
  useEffect(() => {
    if (schema && !selectedMethodId) {
      const first = availableMethods[0] ?? null;
      setSelectedMethodId(first?.id ?? null);
    }
  }, [schema, availableMethods, selectedMethodId]);

  // 3. Form values state
  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Initialize form when method changes
  useEffect(() => {
    if (!selectedMethod) return;
    const merged: Record<string, unknown> = {};
    for (const p of selectedMethod.params) {
      if (p.default !== undefined) {
        merged[p.name] = p.default;
      } else if (p.kind === "boolean") {
        merged[p.name] = false;
      } else if (p.kind === "integer" || p.kind === "float") {
        merged[p.name] = "";
      } else {
        merged[p.name] = "";
      }
    }
    Object.assign(merged, currentParams);
    setFormValues(merged);
    setValidationErrors({});
  }, [selectedMethod, currentParams]);

  // 4. Validation
  const validate = useCallback((): Record<string, string> => {
    const errs: Record<string, string> = {};
    if (!selectedMethod) return errs;
    for (const p of selectedMethod.params) {
      const val = formValues[p.name];
      if (p.required && (val === undefined || val === null || val === "")) {
        errs[p.name] = `${p.label} is required`;
        continue;
      }
      if (val === undefined || val === null || val === "") continue;
      switch (p.kind) {
        case "integer": {
          const n = Number(val);
          if (!Number.isInteger(n)) {
            errs[p.name] = `${p.label} must be an integer`;
          } else {
            if (p.constraint?.min_value !== undefined && n < p.constraint.min_value) {
              errs[p.name] = `${p.label} must be >= ${p.constraint.min_value}`;
            }
            if (p.constraint?.max_value !== undefined && n > p.constraint.max_value) {
              errs[p.name] = `${p.label} must be <= ${p.constraint.max_value}`;
            }
          }
          break;
        }
        case "float": {
          const n = Number(val);
          if (isNaN(n)) {
            errs[p.name] = `${p.label} must be a number`;
          } else {
            if (p.constraint?.min_value !== undefined && n < p.constraint.min_value) {
              errs[p.name] = `${p.label} must be >= ${p.constraint.min_value}`;
            }
            if (p.constraint?.max_value !== undefined && n > p.constraint.max_value) {
              errs[p.name] = `${p.label} must be <= ${p.constraint.max_value}`;
            }
          }
          break;
        }
        case "enum": {
          if (p.constraint?.enum_values && !p.constraint.enum_values.includes(val)) {
            errs[p.name] = `${p.label} must be one of: ${p.constraint.enum_values.join(", ")}`;
          }
          break;
        }
        case "list": {
          if (typeof val === "string") {
            const trimmed = (val as string).trim();
            if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
              try { JSON.parse(trimmed); } catch {
                errs[p.name] = `${p.label} has invalid JSON`;
              }
            }
          }
          break;
        }
        case "object": {
          if (typeof val === "string") {
            try { JSON.parse(val as string); } catch {
              errs[p.name] = `${p.label} must be valid JSON`;
            }
          }
          break;
        }
      }
    }
    return errs;
  }, [selectedMethod, formValues]);

  // 5. Gather params converting form values to proper types
  const gatherParams = useCallback((): Record<string, unknown> => {
    if (!selectedMethod) return {};
    const result: Record<string, unknown> = {};
    for (const p of selectedMethod.params) {
      const val = formValues[p.name];
      if (val === undefined || val === null || val === "") {
        result[p.name] = val;
        continue;
      }
      switch (p.kind) {
        case "integer":
          result[p.name] = parseInt(String(val), 10);
          break;
        case "float":
          result[p.name] = parseFloat(String(val));
          break;
        case "boolean":
          result[p.name] = val === true || val === "true";
          break;
        case "object":
          if (typeof val === "string") {
            try { result[p.name] = JSON.parse(val as string); } catch { result[p.name] = val; }
          } else {
            result[p.name] = val;
          }
          break;
        case "list":
          if (typeof val === "string") {
            const trimmed = (val as string).trim();
            if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
              try { result[p.name] = JSON.parse(trimmed); } catch { result[p.name] = val; }
            } else if (trimmed) {
              result[p.name] = trimmed.split("\n").map((s) => s.trim()).filter(Boolean);
            } else {
              result[p.name] = [];
            }
          } else {
            result[p.name] = val;
          }
          break;
        default:
          result[p.name] = val;
      }
    }
    return result;
  }, [selectedMethod, formValues]);

  // 6. Save mutation
  const saveMutation = useMutation({
    mutationFn: (body: { project_id: string; base_plan_version_id: string; params: Record<string, unknown> }) =>
      api.updateStepParams(planId, stepId, body),
    onSuccess: (resp) => {
      setSuccess(`Saved — new plan version ${resp.new_plan_version_id.slice(0, 8)}… created.`);
      onSaved(resp);
    },
    onError: (err: any) => {
      if (err?.status === 409 && err?.detail?.code === STALE_VERSION_CODE) {
        const latestId: string | undefined = err.detail?.latest_version_id;
        setInfo(
          `Plan modified externally. Refreshing…${latestId ? ` (latest: ${latestId.slice(0, 8)}…)` : ""}`
        );
        onSaved(err.detail);
      } else if (err?.status === 422) {
        setError(err?.detail?.message || "Validation failed");
      } else {
        setError(err?.message || "Save failed");
      }
    },
  });

  const handleSave = () => {
    clearMsg();
    const errs = validate();
    setValidationErrors(errs);
    if (Object.keys(errs).length > 0) return;
    saveMutation.mutate({
      project_id: projectId,
      base_plan_version_id: basePlanVersionId,
      params: gatherParams(),
    });
  };

  const handleChange = (name: string, value: unknown) => {
    setFormValues((prev) => ({ ...prev, [name]: value }));
    setValidationErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const saving = saveMutation.isPending;

  // --- Fallback: raw JSON textarea when schema is unavailable ---
  if (schemaLoading) {
    return (
      <ParamsContainer basePlanVersionId={basePlanVersionId}>
        <div style={{ fontSize: 11, color: "#64748b" }}>Loading schema...</div>
      </ParamsContainer>
    );
  }

  if (schemaError || !schema || !schema.methods || schema.methods.length === 0) {
    return (
      <RawJsonFallback
        planId={planId}
        stepId={stepId}
        projectId={projectId}
        currentParams={currentParams}
        basePlanVersionId={basePlanVersionId}
        onSaved={onSaved}
      />
    );
  }

  return (
    <ParamsContainer basePlanVersionId={basePlanVersionId}>
      {/* Method selector */}
      {schema.methods.length > 1 && (
        <div style={{ marginBottom: 10 }}>
          <label
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "#475569",
              marginBottom: 4,
              display: "block",
            }}
          >
            Method
          </label>
          <select
            value={selectedMethodId ?? ""}
            onChange={(e) => setSelectedMethodId(e.target.value)}
            disabled={saving}
            style={{
              width: "100%",
              padding: "4px 8px",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              fontSize: 12,
              boxSizing: "border-box",
            }}
          >
            {schema.methods.map((m) => (
              <option key={m.id} value={m.id} disabled={m.status === "coming_soon"}>
                {m.label}
                {m.status === "coming_soon" ? " (coming soon)" : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Method description */}
      {selectedMethod?.description && (
        <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8, lineHeight: 1.4 }}>
          {selectedMethod.description}
        </div>
      )}

      {/* Params form */}
      {selectedMethod && selectedMethod.params.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {selectedMethod.params.map((param) => (
            <ParamField
              key={param.name}
              param={param}
              value={formValues[param.name]}
              error={validationErrors[param.name]}
              disabled={saving}
              onChange={(val) => handleChange(param.name, val)}
            />
          ))}
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "#94a3b8" }}>
          {selectedMethod
            ? "No parameters for this method."
            : "No available methods for this node type."}
        </div>
      )}

      <MessageBanner message={msg} type={msgType} />

      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          marginTop: 8,
          padding: "6px 16px",
          borderRadius: 4,
          border: "none",
          backgroundColor: saving ? "#93c5fd" : "#3b82f6",
          color: "#fff",
          fontSize: 12,
          fontWeight: 600,
          cursor: saving ? "not-allowed" : "pointer",
        }}
      >
        {saving ? "Saving..." : "Save Params"}
      </button>
    </ParamsContainer>
  );
}

// --- Sub-components ---

function ParamsContainer({
  basePlanVersionId,
  children,
}: {
  basePlanVersionId: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        borderTop: "1px solid #e2e8f0",
        marginTop: 12,
        paddingTop: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: "#1e293b" }}>
          Parameters
        </span>
        <span
          style={{
            fontSize: 10,
            color: "#94a3b8",
            fontFamily: "monospace",
          }}
        >
          v{basePlanVersionId.slice(0, 8)}…
        </span>
      </div>
      {children}
    </div>
  );
}

function ParamField({
  param,
  value,
  error,
  disabled,
  onChange,
}: {
  param: ParamDefinition;
  value: unknown;
  error?: string;
  disabled: boolean;
  onChange: (val: unknown) => void;
}) {
  const inputStyle: React.CSSProperties = {
    display: "block",
    width: "100%",
    padding: "4px 8px",
    border: error ? "1px solid #dc2626" : "1px solid #d1d5db",
    borderRadius: 4,
    fontSize: 12,
    boxSizing: "border-box",
    backgroundColor: disabled ? "#f1f5f9" : "#fff",
  };

  const renderControl = () => {
    switch (param.kind) {
      case "string":
        return (
          <input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
          />
        );

      case "integer":
      case "float":
        return (
          <input
            type="number"
            step={param.kind === "float" ? "any" : undefined}
            value={value as number | ""}
            disabled={disabled}
            min={param.constraint?.min_value}
            max={param.constraint?.max_value}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            style={inputStyle}
          />
        );

      case "boolean":
        return (
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
            <input
              type="checkbox"
              checked={value === true || value === "true"}
              disabled={disabled}
              onChange={(e) => onChange(e.target.checked)}
            />
            {param.label}
          </label>
        );

      case "enum": {
        const enumValues = (param.constraint?.enum_values ?? []) as string[];
        return (
          <select
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
          >
            <option value="">-- Select --</option>
            {enumValues.map((opt) => (
              <option key={String(opt)} value={String(opt)}>
                {String(opt)}
              </option>
            ))}
          </select>
        );
      }

      case "list": {
        const isComplex =
          param.constraint?.enum_values === undefined &&
          param.constraint?.min_items === undefined;
        const textValue = Array.isArray(value)
          ? (value as string[]).join("\n")
          : typeof value === "string"
            ? value
            : JSON.stringify(value, null, 2) ?? "";
        return (
          <div>
            {isComplex && (
              <div
                style={{
                  fontSize: 10,
                  color: "#64748b",
                  marginBottom: 2,
                }}
              >
                Custom JSON — or one item per line for simple string lists
              </div>
            )}
            <textarea
              value={textValue}
              disabled={disabled}
              rows={4}
              onChange={(e) => onChange(e.target.value)}
              style={{
                ...inputStyle,
                resize: "vertical",
                fontFamily: "monospace",
                fontSize: 11,
                lineHeight: 1.4,
              }}
              spellCheck={false}
            />
          </div>
        );
      }

      case "object": {
        const textValue =
          typeof value === "object" && value !== null
            ? JSON.stringify(value, null, 2)
            : String(value ?? "");
        return (
          <textarea
            value={textValue}
            disabled={disabled}
            rows={4}
            onChange={(e) => onChange(e.target.value)}
            style={{
              ...inputStyle,
              resize: "vertical",
              fontFamily: "monospace",
              fontSize: 11,
              lineHeight: 1.4,
            }}
            spellCheck={false}
          />
        );
      }

      default:
        return (
          <input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
          />
        );
    }
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 2,
        }}
      >
        <label
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "#1e293b",
          }}
        >
          {param.label}
          {param.required && (
            <span style={{ color: "#dc2626", marginLeft: 2 }}>*</span>
          )}
        </label>
        {param.help_text && (
          <span
            title={param.help_text}
            style={{
              fontSize: 10,
              color: "#94a3b8",
              cursor: "help",
            }}
          >
            ⓘ
          </span>
        )}
      </div>
      {renderControl()}
      {error && (
        <div style={{ fontSize: 10, color: "#dc2626", marginTop: 2 }}>
          {error}
        </div>
      )}
    </div>
  );
}

// --- Fallback raw JSON editor (mirrors the original ParamsEditor) ---

function RawJsonFallback({
  planId,
  stepId,
  projectId,
  currentParams,
  basePlanVersionId,
  onSaved,
}: {
  planId: string;
  stepId: string;
  projectId: string;
  currentParams: Record<string, unknown>;
  basePlanVersionId: string;
  onSaved: (resp: UpdateStepParamsResponse | { latest_version_id?: string }) => void;
}) {
  const [text, setText] = useState(JSON.stringify(currentParams, null, 2));
  const prevVersionRef = useRef(basePlanVersionId);
  const { msg, msgType, clearMsg, setError, setInfo, setSuccess } = useMessage();

  useEffect(() => {
    if (basePlanVersionId !== prevVersionRef.current) {
      prevVersionRef.current = basePlanVersionId;
      setText(JSON.stringify(currentParams, null, 2));
      setInfo("Plan refreshed — params have been reloaded.");
    }
  }, [basePlanVersionId, currentParams, setInfo]);

  const saveMutation = useMutation({
    mutationFn: (body: { project_id: string; base_plan_version_id: string; params: Record<string, unknown> }) =>
      api.updateStepParams(planId, stepId, body),
    onSuccess: (resp) => {
      setSuccess(`Saved — new plan version ${resp.new_plan_version_id.slice(0, 8)}… created.`);
      onSaved(resp);
    },
    onError: (err: any) => {
      if (err?.status === 409 && err?.detail?.code === STALE_VERSION_CODE) {
        const latestId: string | undefined = err.detail?.latest_version_id;
        setInfo(
          `Plan modified externally. Refreshing…${latestId ? ` (latest: ${latestId.slice(0, 8)}…)` : ""}`
        );
        onSaved(err.detail);
      } else if (err?.status === 422) {
        setError(err?.detail?.message || "Validation failed");
      } else {
        setError(err?.message || "Save failed");
      }
    },
  });

  const handleSave = () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text);
    } catch {
      setError("Invalid JSON — please fix syntax errors");
      return;
    }
    clearMsg();
    saveMutation.mutate({
      project_id: projectId,
      base_plan_version_id: basePlanVersionId,
      params: parsed,
    });
  };

  const saving = saveMutation.isPending;

  return (
    <ParamsContainer basePlanVersionId={basePlanVersionId}>
      {(!basePlanVersionId || basePlanVersionId === "stale") && (
        <div
          style={{
            padding: "6px 8px",
            backgroundColor: "#fffbeb",
            border: "1px solid #fde68a",
            borderRadius: 4,
            fontSize: 11,
            color: "#92400e",
            marginBottom: 8,
          }}
        >
          Plan version not found — saving may fail with a stale version error.
        </div>
      )}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={saving}
        rows={12}
        style={{
          width: "100%",
          padding: "8px 10px",
          border: "1px solid #d1d5db",
          borderRadius: 4,
          fontSize: 11,
          fontFamily: "monospace",
          resize: "vertical",
          boxSizing: "border-box",
          backgroundColor: saving ? "#f1f5f9" : "#fff",
          color: "#1e293b",
          lineHeight: 1.5,
        }}
        spellCheck={false}
      />

      <MessageBanner message={msg} type={msgType} />

      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          marginTop: 8,
          padding: "6px 16px",
          borderRadius: 4,
          border: "none",
          backgroundColor: saving ? "#93c5fd" : "#3b82f6",
          color: "#fff",
          fontSize: 12,
          fontWeight: 600,
          cursor: saving ? "not-allowed" : "pointer",
        }}
      >
        {saving ? "Saving..." : "Save Params"}
      </button>
    </ParamsContainer>
  );
}
