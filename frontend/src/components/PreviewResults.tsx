import React from 'react';
import type { ManualBinningPreviewResponse } from '../types';

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
        border: `1px solid ${previewData.valid ? "#bbf7d0" : "#fecaca"}`,
        borderRadius: 6,
        backgroundColor: previewData.valid ? "#f0fdf4" : "#fef2f2",
      }}
    >
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: previewData.valid ? "#166534" : "#dc2626",
          marginBottom: 6,
        }}
      >
        {previewData.valid ? "Preview Passed" : "Preview Failed"}
      </div>
      {previewData.diagnostics?.warnings &&
        previewData.diagnostics.warnings.length > 0 && (
        <div style={{ fontSize: 11, color: "#dc2626", marginBottom: 6 }}>
          {previewData.diagnostics.warnings.map((w, i) => (
            <div key={i}>• {w}</div>
          ))}
        </div>
      )}
      {previewData.valid &&
        previewData.refined_bins_by_variable &&
        Object.keys(previewData.refined_bins_by_variable).length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: 11, color: "#166534" }}>
            Show refined bins
          </summary>
          <pre
            style={{
              marginTop: 8,
              padding: 8,
              backgroundColor: "#fff",
              border: "1px solid #e2e8f0",
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
