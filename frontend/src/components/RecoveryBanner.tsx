import React, { useState } from "react";
import { theme } from "../styles";
import { classifyError } from "../utils/errors";
import type { RecoveryInfo } from "../utils/errors";

interface RecoveryBannerProps {
  error: unknown;
  onRetry?: () => void;
  style?: React.CSSProperties;
}

const SEVERITY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  fatal: { bg: theme.redBg, text: theme.redText, border: theme.border },
  user_fixable: { bg: theme.yellowBg, text: theme.yellowText, border: theme.border },
  developer_fixable: { bg: theme.blueBg, text: theme.blueText, border: theme.border },
  retryable: { bg: theme.blueBg, text: theme.blueText, border: theme.border },
};

const DEFAULT_COLOR = { bg: theme.redBg, text: theme.redText, border: theme.border };

function RecoveryBannerInner({ info, onRetry }: { info: RecoveryInfo; onRetry?: () => void }) {
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const colors = SEVERITY_COLORS[info.kind] ?? DEFAULT_COLOR;

  return (
    <div
      style={{
        backgroundColor: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.border}`,
        padding: "12px 16px",
        borderRadius: "6px",
        marginBottom: "16px",
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{info.title}</div>
      <div style={{ opacity: 0.9 }}>{info.message}</div>

      {info.action && info.retryable && onRetry && (
        <button
          onClick={onRetry}
          style={{
            marginTop: 8,
            padding: "4px 12px",
            borderRadius: 4,
            border: `1px solid ${colors.text}`,
            backgroundColor: "transparent",
            color: colors.text,
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          {info.action.label}
        </button>
      )}

      {info.diagnostics && info.diagnostics.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button
            onClick={() => setShowDiagnostics(!showDiagnostics)}
            style={{
              background: "none",
              border: "none",
              color: colors.text,
              fontSize: 11,
              cursor: "pointer",
              padding: 0,
              textDecoration: "underline",
              opacity: 0.7,
            }}
          >
            {showDiagnostics ? "Hide" : "Show"} diagnostics ({info.diagnostics.length})
          </button>
          {showDiagnostics && (
            <pre
              style={{
                marginTop: 4,
                fontSize: 11,
                opacity: 0.8,
                whiteSpace: "pre-wrap",
                fontFamily: theme.fontMono,
                maxHeight: 200,
                overflowY: "auto",
              }}
            >
              {JSON.stringify(info.diagnostics, null, 2)}
            </pre>
          )}
        </div>
      )}

      {(info.requestId || info.errorId) && (
        <div
          style={{
            marginTop: 6,
            fontSize: 10,
            opacity: 0.5,
            fontFamily: theme.fontMono,
          }}
        >
          {info.requestId && <span>req={info.requestId.slice(0, 8)} </span>}
          {info.errorId && <span>err={info.errorId.slice(0, 8)} </span>}
        </div>
      )}
    </div>
  );
}

export function RecoveryBanner({ error, onRetry, style }: RecoveryBannerProps) {
  if (error == null) return null;
  const info = classifyError(error);
  return (
    <div style={style}>
      <RecoveryBannerInner info={info} onRetry={onRetry} />
    </div>
  );
}
