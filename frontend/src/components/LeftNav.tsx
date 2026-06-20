import React from "react";
import { theme } from "../styles";

interface Props {
  activeSection: string;
  onSectionChange: (section: string) => void;
}

const NAV_ITEMS = [
  { id: "pathway", label: "Pathway" },
  { id: "dataset", label: "Dataset" },
  { id: "runs", label: "Runs" },
  { id: "artifacts", label: "Artefacts" },
  { id: "exports", label: "Exports" },
  { id: "diagnostics", label: "Diagnostics" },
];

export function LeftNav({ activeSection, onSectionChange }: Props) {
  return (
    <div
      style={{
        width: 176,
        backgroundColor: theme.canvasSoft,
        borderRight: `1px solid ${theme.border}`,
        padding: "16px 10px",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      {NAV_ITEMS.map((item) => (
        <button
          key={item.id}
          onClick={() => onSectionChange(item.id)}
          style={{
            display: "block",
            width: "100%",
            padding: "8px 10px",
            border: `1px solid ${activeSection === item.id ? theme.border : "transparent"}`,
            borderRadius: 6,
            backgroundColor: activeSection === item.id ? theme.surface : "transparent",
            color: activeSection === item.id ? theme.text : theme.muted,
            fontSize: 12,
            fontWeight: activeSection === item.id ? 600 : 400,
            textAlign: "left",
            cursor: "pointer",
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
