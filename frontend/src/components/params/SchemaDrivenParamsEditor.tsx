import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, isApiError } from "../../api/client";
import type { UpdateStepParamsResponse } from "../../types";
import type { SafeConstraint, SafeDefinition, SafeMethod, SafeSchema } from "./paramsTypes";
import { useMessage } from "../../hooks/useMessage";
import { MessageBanner } from "../MessageBanner";
import { ParamField } from "./ParamField";
import { RawJsonParamsFallback } from "./RawJsonParamsFallback";
import { theme } from "../../styles";

interface Props {
  planId: string;
  stepId: string;
  projectId: string;
  currentParams: Record<string, unknown>;
  basePlanVersionId: string;
  nodeType: string;
  onSaved: (resp: UpdateStepParamsResponse | { latest_version_id?: string }) => void;
}

function normalizeConstraint(c: Record<string, unknown> | null | undefined): SafeConstraint | null {
  if (!c) return null;
  return {
    required: Boolean(c.required),
    min_value: c.min_value as number | undefined,
    max_value: c.max_value as number | undefined,
    exclusive_min: c.exclusive_min as number | undefined,
    exclusive_max: c.exclusive_max as number | undefined,
    min_length: c.min_length as number | undefined,
    max_length: c.max_length as number | undefined,
    min_items: c.min_items as number | undefined,
    max_items: c.max_items as number | undefined,
    enum_values: c.enum_values as unknown[] | undefined,
    pattern: c.pattern as string | null | undefined,
  };
}

function normalizeDefinition(d: Record<string, unknown>): SafeDefinition {
  return {
    name: String(d.name ?? ""),
    label: String(d.label ?? ""),
    kind: String(d.kind ?? "string"),
    default: d.default,
    required: Boolean(d.required),
    constraint: normalizeConstraint(d.constraint as Record<string, unknown> | null | undefined),
    help_text: String(d.help_text ?? ""),
    group: String(d.group ?? ""),
  };
}

function normalizeMethod(m: Record<string, unknown>): SafeMethod {
  return {
    id: String(m.id ?? ""),
    label: String(m.label ?? ""),
    status: (m.status as "available" | "coming_soon") ?? "available",
    params: ((m.params as Record<string, unknown>[]) ?? []).map(normalizeDefinition),
    description: String(m.description ?? ""),
  };
}

function normalizeSchema(raw: Record<string, unknown>): SafeSchema {
  return {
    node_type: String(raw.node_type ?? ""),
    version: String(raw.version ?? ""),
    title: String(raw.title ?? ""),
    methods: ((raw.methods as Record<string, unknown>[]) ?? []).map(normalizeMethod),
    params_schema: (raw.params_schema as Record<string, unknown>) ?? {},
    defaults: (raw.defaults as Record<string, unknown>) ?? {},
    description: String(raw.description ?? ""),
  };
}

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

  const { data: schema, isLoading: schemaLoading, error: schemaError } = useQuery({
    queryKey: ["nodeTypeSchema", nodeType],
    queryFn: async () => {
      const raw = await api.getNodeTypeSchema(nodeType) as Record<string, unknown>;
      return normalizeSchema(raw);
    },
    enabled: !!nodeType,
  });

  const availableMethods = useMemo(
    () => schema?.methods.filter((m) => m.status === "available") ?? [],
    [schema]
  );

  const [selectedMethodId, setSelectedMethodId] = useState<string | null>(null);

  const selectedMethod = useMemo(
    () => (schema?.methods ?? []).find((m) => m.id === selectedMethodId) ?? null,
    [schema, selectedMethodId]
  );

  useEffect(() => {
    if (schema && !selectedMethodId) {
      const currentMethod = currentParams.method as string | undefined;
      if (currentMethod && availableMethods.some((m) => m.id === currentMethod)) {
        setSelectedMethodId(currentMethod);
      } else {
        const first = availableMethods[0] ?? null;
        setSelectedMethodId(first?.id ?? null);
      }
    }
  }, [schema, availableMethods, selectedMethodId, currentParams.method]);

  const [formValues, setFormValues] = useState<Record<string, unknown>>({});
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

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
        case "object": {
          if (typeof val === "string") {
            try { JSON.parse(val as string); } catch { errs[p.name] = `${p.label} must be valid JSON`; }
          }
          break;
        }
      }
    }
    return errs;
  }, [selectedMethod, formValues]);

  const gatherParams = useCallback((): Record<string, unknown> => {
    if (!selectedMethod) return {};
    const result: Record<string, unknown> = {};
    result["method"] = selectedMethod.id;
    for (const p of selectedMethod.params) {
      if (p.name === "method") continue;
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

  const saveMutation = useMutation({
    mutationFn: (body: { project_id: string; base_plan_version_id: string; params: Record<string, unknown> }) =>
      api.updateStepParams(planId, stepId, body),
    onSuccess: (resp) => {
      setSuccess(`Saved — new plan version ${resp.new_plan_version_id.slice(0, 8)}… created.`);
      onSaved(resp);
    },
    onError: (err: unknown) => {
      if (isApiError(err) && err.status === 409 && err.detail.code === "STALE_VERSION") {
        const latestId: string | undefined = err.detail.context?.latest_version_id as string | undefined;
        setInfo(
          `Plan modified externally. Refreshing…${latestId ? ` (latest: ${latestId.slice(0, 8)}…)` : ""}`
        );
        onSaved({ latest_version_id: latestId });
      } else if (isApiError(err) && err.status === 422) {
        setError(err.detail.message || "Validation failed");
      } else {
        setError(isApiError(err) ? err.detail.message : "Save failed");
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

  if (schemaLoading) {
    return (
      <div style={{ borderTop: `1px solid ${theme.border}`, marginTop: 12, paddingTop: 12 }}>
        <div style={{ fontSize: 11, color: theme.muted }}>Loading schema...</div>
      </div>
    );
  }

  if (schemaError || !schema || !schema.methods || schema.methods.length === 0) {
    return (
      <RawJsonParamsFallback
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
    <div style={{ borderTop: `1px solid ${theme.border}`, marginTop: 12, paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: theme.text }}>Parameters</span>
        <span style={{ fontSize: 10, color: theme.mutedSoft, fontFamily: theme.fontMono }}>
          v{basePlanVersionId.slice(0, 8)}…
        </span>
      </div>

      {schema.methods.length > 1 && (
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: theme.textSoft, marginBottom: 4, display: "block" }}>
            Method
          </label>
          <select
            value={selectedMethodId ?? ""}
            onChange={(e) => setSelectedMethodId(e.target.value)}
            disabled={saving}
            style={{
              width: "100%", padding: "4px 8px", border: `1px solid ${theme.borderStrong}`,
              borderRadius: 4, fontSize: 12, boxSizing: "border-box", backgroundColor: theme.surface, color: theme.text,
            }}
          >
            {schema.methods.map((m) => (
              <option key={m.id} value={m.id} disabled={m.status === "coming_soon"}>
                {m.label}{m.status === "coming_soon" ? " (coming soon)" : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      {selectedMethod?.description && (
        <div style={{ fontSize: 11, color: theme.muted, marginBottom: 8, lineHeight: 1.4 }}>
          {selectedMethod.description}
        </div>
      )}

      {selectedMethod && selectedMethod.params.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {selectedMethod.params.filter((p) => p.name !== "method").map((param) => (
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
        <div style={{ fontSize: 11, color: theme.mutedSoft }}>
          {selectedMethod ? "No parameters for this method." : "No available methods for this node type."}
        </div>
      )}

      <MessageBanner message={msg} type={msgType} />

      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          marginTop: 8, padding: "6px 16px", borderRadius: 4, border: "none",
          backgroundColor: saving ? theme.mutedSoft : theme.text, color: "#fff",
          fontSize: 12, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer",
        }}
      >
        {saving ? "Saving..." : "Save Params"}
      </button>
    </div>
  );
}
