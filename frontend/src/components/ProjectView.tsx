import { useProjectWorkspace } from "../hooks/useProjectWorkspace";
import { theme, pageCardStyle } from "../styles";
import { PlanSidebar } from "./PlanSidebar";
import { RunDetailsPanel } from "./RunDetailsPanel";
import { VersionPanel } from "./VersionPanel";

interface Props {
  projectId: string;
  onBack: () => void;
}

export function ProjectView({ projectId, onBack }: Props) {
  const scope = { projectId };
  const ws = useProjectWorkspace(scope);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: theme.canvas,
        padding: 20,
        fontFamily: theme.fontSans,
      }}
    >
      <div style={{ maxWidth: 1400, margin: "0 auto", display: "grid", gap: 16 }}>
        <header
          style={{
            ...pageCardStyle,
            padding: 18,
            display: "flex",
            justifyContent: "space-between",
            gap: 16,
            alignItems: "center",
          }}
        >
          <div>
            <button
              type="button"
              onClick={onBack}
              style={{
                border: `1px solid ${theme.border}`,
                background: theme.surface,
                borderRadius: 999,
                padding: "7px 12px",
                cursor: "pointer",
                color: theme.textSoft,
                marginBottom: 10,
              }}
            >
              Back
            </button>
            <h1 style={{ margin: 0, fontFamily: theme.fontSerif, fontSize: 28 }}>
              {ws.projectQuery.data?.name ?? "Project"}
            </h1>
            <p style={{ margin: "6px 0 0", color: theme.muted, fontSize: 13 }}>{projectId}</p>
          </div>
          <div style={{ textAlign: "right", color: theme.muted, fontSize: 13 }}>
            <div>{ws.projectQuery.data?.cardre_version ?? ""}</div>
            <div>
              {ws.plansQuery.data?.plans.length ?? 0} plans · {ws.runsQuery.data?.runs.length ?? 0}{" "}
              runs
            </div>
          </div>
        </header>

        {ws.error && (
          <div
            style={{
              ...pageCardStyle,
              padding: 14,
              background: theme.redBg,
              color: theme.redText,
            }}
          >
            {ws.error}
          </div>
        )}

        {ws.queryErrorMessage && (
          <div
            style={{
              ...pageCardStyle,
              padding: 14,
              background: theme.yellowBg,
              color: theme.yellowText,
            }}
          >
            {ws.queryErrorMessage}
          </div>
        )}

        <section
          style={{
            display: "grid",
            gridTemplateColumns: "320px minmax(0, 1fr)",
            gap: 16,
            alignItems: "start",
          }}
        >
          <PlanSidebar
            plans={ws.plansQuery.data?.plans}
            plansLoading={ws.plansQuery.isLoading}
            effectiveSelectedPlanId={ws.effectiveSelectedPlanId}
            onSelectPlan={(planId) => {
              ws.setSelectedPlanId(planId);
              ws.setSelectedVersionId(null);
              ws.setSelectedRunId(null);
            }}
            newPlanName={ws.newPlanName}
            onNewPlanNameChange={ws.setNewPlanName}
            onCreatePlan={() => {
              if (!ws.newPlanName.trim()) return;
              ws.createPlanMutation.mutate();
            }}
            createPlanPending={ws.createPlanMutation.isPending}
            runs={ws.visibleRuns}
            versionSelected={!!ws.effectiveSelectedVersionId}
            effectiveSelectedRunId={ws.effectiveSelectedRunId}
            onSelectRun={ws.setSelectedRunId}
          />

          <section style={{ display: "grid", gap: 16 }}>
            <VersionPanel
              selectedPlan={ws.selectedPlan}
              selectedVersion={ws.selectedVersion}
              versionsLoading={ws.versionsQuery.isLoading}
              versions={ws.versionsQuery.data?.versions}
              effectiveSelectedVersionId={ws.effectiveSelectedVersionId}
              onSelectVersion={(versionId) => {
                ws.setSelectedVersionId(versionId);
                ws.setSelectedRunId(null);
              }}
              runPending={ws.runMutation.isPending}
              canRun={!!ws.selectedVersion?.is_committed}
              onRun={() => ws.runMutation.mutate()}
            />

            <RunDetailsPanel
              runLoading={ws.selectedRunQuery.isLoading}
              run={ws.selectedRunQuery.data}
              stepsLoading={ws.runStepsQuery.isLoading}
              steps={ws.runStepsQuery.data}
              evidenceLoading={ws.runEvidenceQuery.isLoading}
              evidence={ws.runEvidenceQuery.data}
            />
          </section>
        </section>
      </div>
    </main>
  );
}
