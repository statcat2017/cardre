import { useCallback } from "react";
import type { WorkflowGuidance } from "../types";

export function useJourneyActions(
  scorecardPlan: Record<string, unknown> | null,
  planData: Record<string, unknown> | null,
  startRun: (planVersionId: string, options?: Record<string, unknown>) => Promise<void>,
  addDiagnostic: (msg: string) => void,
  setActiveSection: (section: string) => void,
  setSelectedStepId: (id: string | null) => void,
  setEditingStepId: (id: string | null) => void,
) {
  const handleJourneyAction = useCallback(
    (g: WorkflowGuidance) => {
      const action = g.next_action;
      switch (action.kind) {
        case "import_dataset":
          setActiveSection("dataset");
          break;
        case "configure_step":
        case "resolve_blocker":
        case "review_evidence":
          if (action.step_id) {
            setSelectedStepId(action.step_id);
            setActiveSection("pathway");
          }
          break;
        case "edit_bins":
          if (action.step_id) {
            setEditingStepId(action.step_id);
            setActiveSection("pathway");
          }
          break;
        case "run_pathway":
          if (scorecardPlan && planData) {
            const scope = action.run_scope ?? "full_plan";
            if (scope === "to_node" && !action.step_id) {
              addDiagnostic("[warning] run_pathway with to_node scope but no step_id — falling back to full_plan");
            }
            startRun(planData.latest_version_id, {
              run_scope: scope,
              target_step_id: scope === "to_node" ? action.step_id ?? undefined : undefined,
              branch_id: g.branch_id ?? undefined,
            });
          }
          break;
        case "export_report":
          setActiveSection("exports");
          break;
        case "resolve_diagnostics":
          setActiveSection("diagnostics");
          break;
      }
    },
    [scorecardPlan, planData, startRun, addDiagnostic, setActiveSection, setSelectedStepId, setEditingStepId],
  );

  return { handleJourneyAction };
}
