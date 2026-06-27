import React from "react";

export const theme = {
  canvas: "#F7F6F3",
  canvasSoft: "#FBFBFA",
  surface: "#FFFFFF",
  surfaceMuted: "#F9F9F8",
  border: "#EAEAEA",
  borderStrong: "rgba(0,0,0,0.12)",
  text: "#111111",
  textSoft: "#2F3437",
  muted: "#787774",
  mutedSoft: "#A6A29D",
  redBg: "#FDEBEC",
  redText: "#9F2F2D",
  blueBg: "#E1F3FE",
  blueText: "#1F6C9F",
  greenBg: "#EDF3EC",
  greenText: "#346538",
  yellowBg: "#FBF3DB",
  yellowText: "#956400",
  fontSans: "'SF Pro Display', 'Geist Sans', 'Helvetica Neue', 'Switzer', sans-serif",
  fontSerif: "'Lyon Text', 'Newsreader', 'Playfair Display', 'Instrument Serif', serif",
  fontMono: "'Geist Mono', 'SF Mono', 'JetBrains Mono', monospace",
};

export const tableHeaderStyle: React.CSSProperties = {
  textAlign: "left",
  fontSize: 10,
  fontWeight: 600,
  color: theme.muted,
  padding: "2px 6px",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};

export const tableDataStyle: React.CSSProperties = {
  fontSize: 10,
  color: theme.textSoft,
  padding: "2px 6px",
  borderBottom: `1px solid ${theme.border}`,
};

export const formInputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 2,
  padding: "4px 8px",
  border: `1px solid ${theme.borderStrong}`,
  borderRadius: 4,
  fontSize: 12,
  boxSizing: "border-box",
  color: theme.text,
  backgroundColor: theme.surface,
};

export const backButtonStyle: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: 4,
  border: `1px solid ${theme.border}`,
  backgroundColor: theme.surface,
  color: theme.textSoft,
  fontSize: 12,
  cursor: "pointer",
};

export const addButtonStyle: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 4,
  border: "none",
  backgroundColor: theme.text,
  color: "#fff",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  alignSelf: "flex-start",
};

export const linkButtonStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: theme.text,
  fontSize: 12,
  cursor: "pointer",
  textDecoration: "underline",
  textUnderlineOffset: 3,
};

export const linkButtonSmallStyle: React.CSSProperties = {
  border: "none",
  background: "none",
  color: theme.text,
  cursor: "pointer",
  fontSize: 11,
  padding: 0,
  textDecoration: "underline",
  textUnderlineOffset: 3,
};

export const preBlockStyle: React.CSSProperties = {
  margin: 0,
  padding: 8,
  backgroundColor: theme.surface,
  border: `1px solid ${theme.border}`,
  borderRadius: 4,
  fontSize: 10,
  maxHeight: 200,
  overflow: "auto",
  color: theme.textSoft,
  fontFamily: theme.fontMono,
};

export const pageButtonStyle = (disabled: boolean): React.CSSProperties => ({
  padding: "2px 8px",
  borderRadius: 3,
  border: `1px solid ${disabled ? theme.border : theme.borderStrong}`,
  backgroundColor: disabled ? theme.canvasSoft : theme.surface,
  color: disabled ? theme.mutedSoft : theme.textSoft,
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 11,
});
