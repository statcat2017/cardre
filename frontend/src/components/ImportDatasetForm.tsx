import React, { useState } from "react";
import { useImportDataset } from "../hooks/useImportDataset";
import { theme } from "../styles";

interface Props {
  projectId: string;
  onImported: () => void;
  onError?: (e: Error) => void;
  headerContent?: React.ReactNode;
  successContent?: React.ReactNode;
  label?: string;
  placeholder?: string;
}

export function ImportDatasetForm({
  projectId,
  onImported,
  onError,
  headerContent,
  successContent,
  label = "Source File Path",
  placeholder = "/path/to/applications.csv",
}: Props) {
  const [importPath, setImportPath] = useState("");
  const [error, setError] = useState<string | null>(null);

  const importMutation = useImportDataset(
    () => {
      setError(null);
      onImported();
    },
    (e) => {
      setError(e.message);
      onError?.(e);
    },
  );

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
    <div style={{ padding: 24, maxWidth: 620 }}>
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: theme.text }}>Import Dataset</h3>
      <div
        style={{
          padding: 24,
          border: `1px solid ${theme.border}`,
          borderRadius: 12,
          backgroundColor: theme.surface,
        }}
      >
        {headerContent}

        <div style={{ marginBottom: 12 }}>
          <label style={{ display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: theme.textSoft }}>
            {label}
          </label>
          <input
            type="text"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
            placeholder={placeholder}
            style={{
              width: "100%",
              padding: "10px 12px",
              border: `1px solid ${theme.borderStrong}`,
              borderRadius: 6,
              fontSize: 13,
              boxSizing: "border-box",
              color: theme.text,
              backgroundColor: theme.surface,
            }}
          />
        </div>

        {error && (
          <div
            style={{
              padding: "8px 12px",
              backgroundColor: theme.redBg,
              color: theme.redText,
              border: `1px solid ${theme.border}`,
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
            backgroundColor: importMutation.isPending ? theme.mutedSoft : theme.text,
            color: "#fff",
            fontSize: 13,
            fontWeight: 600,
            cursor: importMutation.isPending ? "not-allowed" : "pointer",
          }}
        >
          {importMutation.isPending ? "Importing..." : "Import"}
        </button>

        {importMutation.isSuccess && successContent && (
          <div
            style={{
              marginTop: 12,
              padding: "8px 12px",
              backgroundColor: theme.greenBg,
              color: theme.greenText,
              border: `1px solid ${theme.border}`,
              borderRadius: 4,
              fontSize: 12,
            }}
          >
            {successContent}
          </div>
        )}
      </div>
    </div>
  );
}
