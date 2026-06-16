import React from 'react';

export const tableHeaderStyle: React.CSSProperties = {
  textAlign: "left",
  fontSize: 10,
  fontWeight: 600,
  color: "#64748b",
  padding: "2px 6px",
};

export const tableDataStyle: React.CSSProperties = {
  fontSize: 10,
  color: "#334155",
  padding: "2px 6px",
  borderBottom: "1px solid #f1f5f9",
};

export const formInputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 2,
  padding: "4px 8px",
  border: "1px solid #d1d5db",
  borderRadius: 4,
  fontSize: 12,
  boxSizing: "border-box",
};

export const backButtonStyle: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: 4,
  border: "1px solid #e2e8f0",
  backgroundColor: "#fff",
  color: "#475569",
  fontSize: 12,
  cursor: "pointer",
};

export const addButtonStyle: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 4,
  border: "none",
  backgroundColor: "#3b82f6",
  color: "#fff",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  alignSelf: "flex-start",
};

export const linkButtonStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "#3b82f6",
  fontSize: 12,
  cursor: "pointer",
  textDecoration: "underline",
};

export const linkButtonSmallStyle: React.CSSProperties = {
  border: "none",
  background: "none",
  color: "#3b82f6",
  cursor: "pointer",
  fontSize: 11,
  padding: 0,
  textDecoration: "underline",
};

export const preBlockStyle: React.CSSProperties = {
  margin: 0,
  padding: 8,
  backgroundColor: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 4,
  fontSize: 10,
  maxHeight: 200,
  overflow: "auto",
  color: "#334155",
};

export const pageButtonStyle = (disabled: boolean): React.CSSProperties => ({
  padding: "2px 8px",
  borderRadius: 3,
  border: `1px solid ${disabled ? "#e2e8f0" : "#cbd5e1"}`,
  backgroundColor: disabled ? "#f8fafc" : "#fff",
  color: disabled ? "#94a3b8" : "#475569",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 11,
});
