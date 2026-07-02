import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function App() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        fontFamily: "system-ui, sans-serif",
        background: "#f6f3ee",
        color: "#1f1f1f",
      }}
    >
      <section style={{ maxWidth: 720, padding: "3rem 2rem", textAlign: "center" }}>
        <p style={{ letterSpacing: "0.18em", textTransform: "uppercase", fontSize: "0.75rem" }}>
          Cardre
        </p>
        <h1 style={{ fontSize: "clamp(2.5rem, 8vw, 5rem)", lineHeight: 1.02, margin: "0.5rem 0" }}>
          Evidence-first scorecard workflows.
        </h1>
        <p style={{ fontSize: "1.05rem", lineHeight: 1.7, maxWidth: 560, margin: "0 auto" }}>
          The Vite entrypoint is restored so the frontend can build again.
        </p>
      </section>
    </main>
  );
}

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing root element");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
