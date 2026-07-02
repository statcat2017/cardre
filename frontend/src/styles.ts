import type React from "react";

export const theme = {
  canvas: "#f7f6f3",
  canvasSoft: "#fbfbfa",
  surface: "#ffffff",
  surfaceMuted: "#f9f9f8",
  border: "#eaeaea",
  borderStrong: "rgba(0,0,0,0.12)",
  text: "#111111",
  textSoft: "#2f3437",
  muted: "#787774",
  mutedSoft: "#a6a29d",
  redBg: "#fdebec",
  redText: "#9f2f2d",
  blueBg: "#e1f3fe",
  blueText: "#1f6c9f",
  greenBg: "#edf3ec",
  greenText: "#346538",
  yellowBg: "#fbf3db",
  yellowText: "#956400",
  fontSans: "'SF Pro Display', 'Geist Sans', 'Helvetica Neue', 'Switzer', sans-serif",
  fontSerif: "'Lyon Text', 'Newsreader', 'Playfair Display', 'Instrument Serif', serif",
  fontMono: "'Geist Mono', 'SF Mono', 'JetBrains Mono', monospace",
};

export const pageCardStyle: React.CSSProperties = {
  border: `1px solid ${theme.border}`,
  borderRadius: 16,
  backgroundColor: theme.surface,
  boxShadow: "0 1px 0 rgba(0,0,0,0.02)",
};

export const panelStyle: React.CSSProperties = {
  border: `1px solid ${theme.border}`,
  borderRadius: 12,
  backgroundColor: theme.surface,
};
