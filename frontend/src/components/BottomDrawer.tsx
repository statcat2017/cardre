import React from "react";

interface Props {
  messages: string[];
}

export function BottomDrawer({ messages }: Props) {
  if (messages.length === 0) return null;

  return (
    <div
      style={{
        height: 100,
        borderTop: "1px solid #e2e8f0",
        backgroundColor: "#1e293b",
        color: "#94a3b8",
        padding: "8px 16px",
        overflowY: "auto",
        flexShrink: 0,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, color: "#64748b", marginBottom: 4 }}>
        Diagnostics
      </div>
      {messages.map((msg, i) => (
        <div key={i} style={{ fontSize: 11, fontFamily: "monospace", lineHeight: 1.5 }}>
          {msg}
        </div>
      ))}
    </div>
  );
}
