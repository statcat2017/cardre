import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { ProjectView } from "./components/ProjectView";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { pageCardStyle, theme } from "./styles";

declare global {
  interface Window {
    __SIDECAR_STARTUP_ERROR__?: string;
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 2_000,
    },
  },
});

export { queryClient };

function AppContent() {
  const [projectId, setProjectId] = useState<string | null>(null);

  if (window.__SIDECAR_STARTUP_ERROR__) {
    return (
      <main
        role="alert"
        style={{
          minHeight: "100vh",
          padding: 32,
          boxSizing: "border-box",
          background: theme.canvas,
          color: theme.text,
          fontFamily: theme.fontSans,
        }}
      >
        <section
          style={{
            ...pageCardStyle,
            maxWidth: 760,
            margin: "48px auto",
            padding: 24,
          }}
        >
          <h1 style={{ marginTop: 0, fontSize: 22 }}>Cardre could not start its local API</h1>
          <p style={{ lineHeight: 1.6 }}>
            The desktop app could not start the bundled Cardre API service. Reinstall the app or
            contact support with this error:
          </p>
          <pre
            style={{
              padding: 12,
              overflowWrap: "anywhere",
              whiteSpace: "pre-wrap",
              borderRadius: 8,
              background: theme.redBg,
              color: theme.redText,
            }}
          >
            {window.__SIDECAR_STARTUP_ERROR__}
          </pre>
        </section>
      </main>
    );
  }

  if (projectId) {
    return <ProjectView projectId={projectId} onBack={() => setProjectId(null)} />;
  }

  return <WelcomeScreen onProjectCreated={(nextProjectId) => setProjectId(nextProjectId)} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
