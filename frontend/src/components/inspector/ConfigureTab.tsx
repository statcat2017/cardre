import React from "react";
import { SchemaDrivenParamsEditor } from "../params/SchemaDrivenParamsEditor";
import type { UpdateStepParamsResponse } from "../../types";

interface Props {
  stepId: string;
  nodeType: string;
  planId: string;
  projectId: string;
  basePlanVersionId: string;
  currentParams: Record<string, unknown>;
  onPlanRefreshed: (detailOrResp: UpdateStepParamsResponse | { latest_version_id?: string }) => void;
}

export function ConfigureTab({ stepId, nodeType, planId, projectId, basePlanVersionId, currentParams, onPlanRefreshed }: Props) {
  return (
    <SchemaDrivenParamsEditor
      key={`${stepId}:${nodeType}`}
      planId={planId}
      stepId={stepId}
      projectId={projectId}
      currentParams={currentParams}
      basePlanVersionId={basePlanVersionId}
      nodeType={nodeType}
      onSaved={onPlanRefreshed}
    />
  );
}
