import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { linkButtonSmallStyle, preBlockStyle, pageButtonStyle, theme } from "../styles";
import { RecoveryBanner } from "./RecoveryBanner";

const LARGE_ROW_THRESHOLD = 100_000;
const HARD_ROW_CAP = 1_000_000;

interface Props {
  projectId: string;
  artifactId: string;
  mediaType: string;
  rowCount: number | null | undefined;
  summaryPreview: Record<string, unknown> | null | undefined;
}

export function ArtifactPreviewPane({
  projectId,
  artifactId,
  mediaType,
  rowCount,
  summaryPreview,
}: Props) {
  const [showPreview, setShowPreview] = useState(false);
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);

  const {
    data: preview,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["artifactPreview", projectId, artifactId, limit, offset],
    queryFn: () => api.getProjectArtifactPreview(projectId, artifactId, limit, offset),
    enabled: showPreview,
  });

  const total = rowCount ?? preview?.row_count ?? 0;
  const isLarge = total > LARGE_ROW_THRESHOLD;
  const isTooLarge = total > HARD_ROW_CAP;

  if (summaryPreview) {
    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ color: theme.muted, marginBottom: 2 }}>Summary Preview</div>
        <pre style={preBlockStyle}>{JSON.stringify(summaryPreview, null, 2)}</pre>
      </div>
    );
  }

  if (mediaType === "application/vnd.apache.parquet" || mediaType === "application/json") {
    if (isTooLarge) {
      return (
        <div
          style={{
            marginTop: 8,
            padding: "8px 12px",
            backgroundColor: theme.yellowBg,
            border: `1px solid ${theme.border}`,
            borderRadius: 6,
            fontSize: 12,
            color: theme.yellowText,
          }}
        >
          Dataset has {total.toLocaleString()} rows - too large to preview. Use the summary endpoint
          or download the artifact directly.
        </div>
      );
    }
    return (
      <div style={{ marginTop: 8 }}>
        {!showPreview ? (
          <button onClick={() => setShowPreview(true)} style={linkButtonSmallStyle}>
            {isLarge
              ? `Show Data Preview (${total.toLocaleString()} rows - may be slow for large artifacts)`
              : "Show Data Preview"}
          </button>
        ) : isLoading ? (
          <div style={{ color: theme.muted, fontSize: 11 }}>Loading preview...</div>
        ) : isError ? (
          <RecoveryBanner error={error} onRetry={() => refetch()} />
        ) : preview ? (
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 4,
              }}
            >
              <span style={{ fontSize: 11, color: theme.muted }}>
                Showing rows {offset + 1}–{Math.min(offset + limit, total)} of{" "}
                {total.toLocaleString()}
              </span>
              <div style={{ display: "flex", gap: 4 }}>
                <button
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  disabled={offset === 0}
                  style={pageButtonStyle(offset === 0)}
                >
                  Prev
                </button>
                <button
                  onClick={() => setOffset(offset + limit)}
                  disabled={offset + limit >= total}
                  style={pageButtonStyle(offset + limit >= total)}
                >
                  Next
                </button>
              </div>
            </div>
            {preview.rows && preview.rows.length > 0 && preview.columns && (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10 }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${theme.border}` }}>
                      {preview.columns.map((c: { name: string; dtype: string }) => (
                        <th
                          key={c.name}
                          style={{
                            textAlign: "left",
                            padding: "4px 6px",
                            color: theme.textSoft,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {c.name}
                          <br />
                          <span style={{ fontWeight: 400, color: theme.mutedSoft }}>{c.dtype}</span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row: Record<string, unknown>, ri: number) => (
                      <tr key={ri} style={{ borderBottom: `1px solid ${theme.border}` }}>
                        {preview.columns!.map((c: { name: string }) => (
                          <td
                            key={c.name}
                            style={{
                              padding: "3px 6px",
                              color: theme.textSoft,
                              maxWidth: 200,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {row[c.name] !== null && row[c.name] !== undefined
                              ? String(row[c.name])
                              : "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {preview.json_content && (
              <pre style={preBlockStyle}>{JSON.stringify(preview.json_content, null, 2)}</pre>
            )}
            {!preview.rows?.length && !preview.json_content && (
              <div style={{ color: theme.mutedSoft, fontSize: 11 }}>No preview data available.</div>
            )}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div
      style={{
        marginTop: 8,
        padding: "8px 12px",
        backgroundColor: theme.canvasSoft,
        border: `1px solid ${theme.border}`,
        borderRadius: 6,
        fontSize: 12,
        color: theme.muted,
      }}
    >
      Preview not supported for media type <code>{mediaType}</code>. Use the summary endpoint or
      download the artifact directly.
    </div>
  );
}
