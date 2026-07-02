import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { ProjectView } from "./components/ProjectView";
import { WelcomeScreen } from "./components/WelcomeScreen";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 2_000,
    },
  },
});

function AppContent() {
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);

  if (projectPath && projectId) {
    return (
      <ProjectView
        projectPath={projectPath}
        projectId={projectId}
        onBack={() => {
          setProjectId(null);
        }}
      />
    );
  }

  return (
    <WelcomeScreen
      onProjectCreated={(nextProjectId, nextProjectPath) => {
        setProjectId(nextProjectId);
        setProjectPath(nextProjectPath);
      }}
    />
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
