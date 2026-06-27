import React from "react";
import { theme } from "../styles";

interface Props {
  messages: string[];
}

export function BottomDrawer({ messages }: Props) {
  if (messages.length === 0) return null;

  return (
    <div
      style={{
        height: 100,
        borderTop: `1px solid ${theme.border}`,
        backgroundColor: theme.surface,
        color: theme.muted,
        padding: "8px 16px",
        overflowY: "auto",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: theme.textSoft,
          marginBottom: 4,
          letterSpacing: "0.05em",
          textTransform: "uppercase",
        }}
      >
        Diagnostics
      </div>
      {messages.map((msg, i) => (
        <div key={i} style={{ fontSize: 11, fontFamily: theme.fontMono, lineHeight: 1.5 }}>
          {msg}
        </div>
      ))}
    </div>
  );
}
