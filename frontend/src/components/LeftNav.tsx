import React from "react";

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
        width: 160,
        backgroundColor: "#f1f5f9",
        borderRight: "1px solid #e2e8f0",
        padding: "12px 0",
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {NAV_ITEMS.map((item) => (
        <button
          key={item.id}
          onClick={() => onSectionChange(item.id)}
          style={{
            display: "block",
            width: "100%",
            padding: "8px 16px",
            border: "none",
            backgroundColor: activeSection === item.id ? "#e0e7ff" : "transparent",
            color: activeSection === item.id ? "#3730a3" : "#475569",
            fontSize: 13,
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
