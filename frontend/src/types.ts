// Auto-generated from backend OpenAPI schema via scripts/generate-openapi-types.py
// DO NOT EDIT MANUALLY — all types derive from schema.d.ts
//
// Run `python3 scripts/generate-openapi-types.py` to regenerate from the backend spec.

import type { components } from './api/schema';

type S = components['schemas'];

// --- Schema types (auto-generated from Pydantic models) ---

export type HealthResponse = S['HealthResponse'];
export type ProjectResponse = S['ProjectResponse'];
export type ProjectDetailResponse = S['ProjectDetailResponse'];
export type PlanListItem = S['PlanListItem'];
export type ProjectPlansResponse = S['ProjectPlansResponse'];
export type StepStatus = S['StepStatusItem'];
export type PlanResponse = S['PlanResponse'];
export type RunResponse = S['RunResponse'];
export type RunStepItem = S['RunStepItem'];
export type RunStepsResponse = S['RunStepsResponse'];
export type ArtifactResponse = S['ArtifactResponse'];
export type UpdateStepParamsResponse = S['UpdateStepParamsResponse'];
export type RunListItem = S['RunListItem'];
export type ProjectRunsResponse = S['ProjectRunsResponse'];
export type ArtifactListItem = S['ArtifactListItem'];
export type ProjectArtifactsResponse = S['ProjectArtifactsResponse'];
export type ArtifactSummaryResponse = S['ArtifactSummaryResponse'];
export type ColumnInfo = S['ColumnInfo'];
export type ArtifactPreviewResponse = S['ArtifactPreviewResponse'];
export type ManualBinningSourceInfo = S['ManualBinningSourceInfo'];
export type ManualBinningEditorStateResponse = S['ManualBinningEditorStateResponse'];
export type PreviewDiagnostics = S['PreviewDiagnostics'];
export type ManualBinningPreviewResponse = S['ManualBinningPreviewResponse'];
export type BranchStepItem = S['BranchStepItem'];
export type BranchResponse = S['BranchResponse'];
export type BranchListItem = S['BranchListItem'];
export type BranchListResponse = S['BranchListResponse'];
export type MigrateResponse = S['MigrateResponse'];
export type CreateBranchResponse = S['CreateBranchResponse'];
export type ComparisonResponse = S['ComparisonResponse'];
export type RefreshComparisonResponse = S['RefreshComparisonResponse'];
export type ComparisonSnapshotResponse = S['ComparisonSnapshotResponse'];
export type ChampionResponse = S['ChampionResponse'];
export type ExportAuditPackResponse = S['ExportAuditPackResponse'];
export type ReportReadinessItem = S['ReadinessItem'];
export type ReportReadinessResponse = S['ReportReadinessResponse'];
export type GenerateReportResponse = S['GenerateReportResponse'];
export type MethodSummaryResponse = S['MethodSummaryResponse'];
export type ModelRankingResponse = S['ModelRankingResponse'];
export type NodeTypeListResponse = S['NodeTypeListResponse'];
export type NodeTypeSchemaResponse = S['NodeTypeSchemaResponse'];

// --- Request body types (aliased from schema request schemas) ---

export type CreateProjectBody = S['CreateProjectRequest'];
export type ImportBody = S['ImportDatasetRequest'];
export type UpdateStepParamsBody = S['UpdateStepParamsRequest'];
export type RunBody = S['RunRequest'];
export type ManualBinningPreviewBody = S['ManualBinningPreviewRequest'];
export type CreateBranchBody = S['CreateBranchRequest'];
export type AssignChampionBody = S['AssignChampionRequest'];
export type ExportAuditPackBody = S['ExportAuditPackRequest'];

// --- Manual types (no exact schema equivalent) ---

export type StepStatusCode =
  | "not_run"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";
