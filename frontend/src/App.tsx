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
  const [projectId, setProjectId] = useState<string | null>(null);

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
