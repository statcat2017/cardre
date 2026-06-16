import React, { useState, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import type { UpdateStepParamsResponse } from "../types";
import { useMessage } from "../hooks/useMessage";
import { MessageBanner } from "./MessageBanner";

interface Props {
  planId: string;
  stepId: string;
  projectId: string;
  currentParams: Record<string, unknown>;
  basePlanVersionId: string;
  onSaved: (resp: UpdateStepParamsResponse | { latest_version_id?: string }) => void;
}

const STALE_VERSION_CODE = "STALE_VERSION";

export function ParamsEditor({
  planId,
  stepId,
  projectId,
  currentParams,
  basePlanVersionId,
  onSaved,
}: Props) {
  const [text, setText] = useState(JSON.stringify(currentParams, null, 2));
  const prevVersionRef = useRef(basePlanVersionId);
  const { msg, msgType, clearMsg, setError, setInfo, setSuccess } = useMessage();

  useEffect(() => {
    if (basePlanVersionId !== prevVersionRef.current) {
      prevVersionRef.current = basePlanVersionId;
      setText(JSON.stringify(currentParams, null, 2));
      setInfo("Plan refreshed — params have been reloaded. You can try saving again.");
    }
  }, [basePlanVersionId, currentParams]);

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
          `Plan was modified externally. Refreshing…${latestId ? ` (latest: ${latestId.slice(0, 8)}…)` : ""}`
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
        <span style={{ fontSize: 10, color: "#94a3b8", fontFamily: "monospace" }}>
          v{basePlanVersionId.slice(0, 8)}…
        </span>
      </div>

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
    </div>
  );
}
