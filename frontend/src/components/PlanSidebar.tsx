import type { components } from "../api/schema.d";
import { theme, pageCardStyle } from "../styles";

type Plan = Pick<components["schemas"]["PlanResponse"], "plan_id" | "name">;
type Run = Pick<components["schemas"]["RunResponse"], "run_id" | "status">;

interface Props {
  plans: Plan[] | undefined;
  plansLoading: boolean;
  effectiveSelectedPlanId: string | null;
  onSelectPlan: (planId: string) => void;
  newPlanName: string;
  onNewPlanNameChange: (name: string) => void;
  onCreatePlan: () => void;
  createPlanPending: boolean;
  runs: Run[];
  versionSelected: boolean;
  effectiveSelectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}

export function PlanSidebar({
  plans,
  plansLoading,
  effectiveSelectedPlanId,
  onSelectPlan,
  newPlanName,
  onNewPlanNameChange,
  onCreatePlan,
  createPlanPending,
  runs,
  versionSelected,
  effectiveSelectedRunId,
  onSelectRun,
}: Props) {
  const displayRuns = runs;

  return (
    <aside style={{ ...pageCardStyle, padding: 16, display: "grid", gap: 16 }}>
      <div>
        <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Plans</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onCreatePlan();
          }}
          style={{ display: "grid", gap: 8, marginBottom: 12 }}
        >
          <input
            value={newPlanName}
            onChange={(event) => onNewPlanNameChange(event.target.value)}
            placeholder="New plan name"
            style={{
              width: "100%",
              padding: "10px 12px",
              borderRadius: 10,
              border: `1px solid ${theme.borderStrong}`,
              boxSizing: "border-box",
            }}
          />
          <button
            type="submit"
            disabled={createPlanPending}
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: 0,
              background: theme.text,
              color: "#fff",
              cursor: createPlanPending ? "not-allowed" : "pointer",
            }}
          >
            {createPlanPending ? "Creating..." : "Create plan"}
          </button>
        </form>

        <div style={{ display: "grid", gap: 8 }}>
          {plansLoading ? (
            <div style={{ color: theme.muted, fontSize: 14 }}>Loading plans...</div>
          ) : plans?.length ? (
            plans.map((plan) => (
              <button
                key={plan.plan_id}
                type="button"
                onClick={() => onSelectPlan(plan.plan_id)}
                style={{
                  textAlign: "left",
                  padding: 12,
                  borderRadius: 12,
                  border: `1px solid ${plan.plan_id === effectiveSelectedPlanId ? theme.text : theme.border}`,
                  background:
                    plan.plan_id === effectiveSelectedPlanId ? theme.canvasSoft : theme.surface,
                  cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: 600 }}>{plan.name}</div>
                <div style={{ color: theme.muted, fontSize: 12 }}>{plan.plan_id}</div>
              </button>
            ))
          ) : (
            <div style={{ color: theme.muted, fontSize: 14 }}>No plans yet.</div>
          )}
        </div>
      </div>

      <div>
        <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Runs</h2>
        <div style={{ display: "grid", gap: 8 }}>
          {displayRuns.length > 0 ? (
            displayRuns.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => onSelectRun(run.run_id)}
                style={{
                  textAlign: "left",
                  padding: 12,
                  borderRadius: 12,
                  border: `1px solid ${run.run_id === effectiveSelectedRunId ? theme.text : theme.border}`,
                  background:
                    run.run_id === effectiveSelectedRunId ? theme.canvasSoft : theme.surface,
                  cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: 600 }}>{run.status}</div>
                <div style={{ color: theme.muted, fontSize: 12 }}>{run.run_id}</div>
              </button>
            ))
          ) : (
            <div style={{ color: theme.muted, fontSize: 14 }}>
              {versionSelected ? "No runs for this version." : "No runs yet."}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
