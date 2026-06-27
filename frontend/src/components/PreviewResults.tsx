import React from "react";
import type { ManualBinningPreviewResponse } from "../types";
import { theme } from "../styles";

interface Props {
  previewData: ManualBinningPreviewResponse | undefined;
}

export function PreviewResults({ previewData }: Props) {
  if (!previewData) return null;

  return (
    <div
      style={{
        marginBottom: 16,
        padding: 12,
        border: `1px solid ${theme.border}`,
        borderRadius: 6,
        backgroundColor: previewData.valid ? theme.greenBg : theme.redBg,
      }}
    >
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: previewData.valid ? theme.greenText : theme.redText,
          marginBottom: 6,
        }}
      >
        {previewData.valid ? "Preview Passed" : "Preview Failed"}
      </div>
      {previewData.diagnostics?.warnings && previewData.diagnostics.warnings.length > 0 && (
        <div style={{ fontSize: 11, color: theme.redText, marginBottom: 6 }}>
          {previewData.diagnostics.warnings.map((w, i) => (
            <div key={i}>Warning: {w}</div>
          ))}
        </div>
      )}
      {previewData.valid &&
        previewData.refined_bins_by_variable &&
        Object.keys(previewData.refined_bins_by_variable).length > 0 && (
          <details>
            <summary style={{ cursor: "pointer", fontSize: 11, color: theme.greenText }}>
              Show refined bins
            </summary>
            <pre
              style={{
                marginTop: 8,
                padding: 8,
                backgroundColor: theme.surface,
                border: `1px solid ${theme.border}`,
                borderRadius: 4,
                fontSize: 10,
                maxHeight: 300,
                overflow: "auto",
              }}
            >
              {JSON.stringify(previewData.refined_bins_by_variable, null, 2)}
            </pre>
          </details>
        )}
    </div>
  );
}
