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
  const [project, setProject] = useState<{ id: string; path: string } | null>(null);

  if (project) {
    return (
      <ProjectView
        projectPath={project.path}
        projectId={project.id}
        onBack={() => setProject(null)}
      />
    );
  }

  return (
    <WelcomeScreen
      onProjectCreated={(nextProjectId, nextProjectPath) => {
        setProject({ id: nextProjectId, path: nextProjectPath });
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
