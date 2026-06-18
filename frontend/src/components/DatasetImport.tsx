import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  projectId: string;
  onImported: () => void;
}

export function DatasetImport({ projectId, onImported }: Props) {
  const [importPath, setImportPath] = useState("");
  const [error, setError] = useState<string | null>(null);

  const importMutation = useMutation({
    mutationFn: (body: { project_id: string; source_path: string }) =>
      api.importDataset({
        ...body,
        dataset_id: "",
        format: "auto",
        has_header: true,
        schema_overrides: {},
      }),
    onSuccess: () => {
      setError(null);
      onImported();
    },
    onError: (e: Error) => setError(e.message),
  });

  const handleImport = () => {
    if (!importPath.trim()) {
      setError("Please enter a file path");
      return;
    }
    setError(null);
    importMutation.mutate({
      project_id: projectId,
      source_path: importPath.trim(),
    });
  };

  return (
    <div style={{ padding: 16, maxWidth: 560 }}>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Import Dataset</h3>
      <div
        style={{
          padding: 16,
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          backgroundColor: "#fff",
        }}
      >
        <div style={{ marginBottom: 12 }}>
          <label style={{ display: "block", fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
            Source File Path
          </label>
          <input
            type="text"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
            placeholder="/path/to/applications.csv"
            style={{
              width: "100%",
              padding: "8px 12px",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              fontSize: 13,
              boxSizing: "border-box",
            }}
          />
        </div>

        {error && (
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: "#fef2f2",
              color: "#dc2626",
              borderRadius: 4,
              marginBottom: 12,
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}

        <button
          onClick={handleImport}
          disabled={importMutation.isPending}
          style={{
            padding: "8px 16px",
            borderRadius: 4,
            border: "none",
            backgroundColor: importMutation.isPending ? "#93c5fd" : "#3b82f6",
            color: "#fff",
            fontSize: 13,
            fontWeight: 600,
            cursor: importMutation.isPending ? "not-allowed" : "pointer",
          }}
        >
          {importMutation.isPending ? "Importing..." : "Import"}
        </button>

        {importMutation.isSuccess && (
          <div
            style={{
              marginTop: 12,
              padding: "8px 12px",
              backgroundColor: "#f0fdf4",
              color: "#166534",
              borderRadius: 4,
              fontSize: 12,
            }}
          >
            Dataset imported and registered. The Scorecard Pathway import step has been configured.
            Run the pathway to create run evidence.
          </div>
        )}
      </div>
    </div>
  );
}
