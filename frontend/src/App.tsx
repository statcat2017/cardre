import React, { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { ProjectView } from "./components/ProjectView";
import { theme } from "./styles";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 2000 } },
});

function AppContent() {
  const [projectId, setProjectId] = useState<string | null>(null);

  if (projectId) {
    return <ProjectView projectId={projectId} onBack={() => setProjectId(null)} />;
  }

  return <WelcomeScreen onProjectCreated={setProjectId} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div
        style={{
          minHeight: "100vh",
          backgroundColor: theme.canvas,
          color: theme.text,
          fontFamily: theme.fontSans,
          lineHeight: 1.6,
        }}
      >
        <AppContent />
      </div>
    </QueryClientProvider>
  );
}
