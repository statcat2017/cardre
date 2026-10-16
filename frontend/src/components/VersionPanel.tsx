import type { components } from "../api/schema.d";
import { theme, pageCardStyle } from "../styles";

type Version = Pick<
  components["schemas"]["PlanVersionResponse"],
  "plan_version_id" | "version_number" | "is_committed" | "description"
>;
type SelectedPlan = Pick<components["schemas"]["PlanResponse"], "plan_id" | "name">;
type SelectedVersion = Pick<
  components["schemas"]["PlanVersionResponse"],
  "plan_version_id" | "version_number" | "is_committed"
>;
type ImportedDataset = Pick<
  components["schemas"]["DatasetImportResponse"],
  "source_ref" | "file_name" | "size_bytes"
>;

interface Props {
  selectedPlan: SelectedPlan | null;
  selectedVersion: SelectedVersion | null;
  versionsLoading: boolean;
  versions: Version[] | undefined;
  effectiveSelectedVersionId: string | null;
  onSelectVersion: (versionId: string) => void;
  runPending: boolean;
  canRun: boolean;
  onRun: () => void;
  selectedDataset: ImportedDataset | null;
  datasetImportingName: string | null;
  datasetImportPending: boolean;
  datasetImportError: string | null;
  onDatasetFile: (file: File) => void;
  targetColumn: string;
  onTargetColumnChange: (value: string) => void;
  goodValues: string;
  onGoodValuesChange: (value: string) => void;
  badValues: string;
  onBadValuesChange: (value: string) => void;
  onGeneratePathway: () => void;
  generatePathwayPending: boolean;
  onCommit: () => void;
  commitPending: boolean;
}

export function VersionPanel({
  selectedPlan,
  selectedVersion,
  versionsLoading,
  versions,
  effectiveSelectedVersionId,
  onSelectVersion,
  runPending,
  canRun,
  onRun,
  selectedDataset,
  datasetImportingName,
  datasetImportPending,
  datasetImportError,
  onDatasetFile,
  targetColumn,
  onTargetColumnChange,
  goodValues,
  onGoodValuesChange,
  badValues,
  onBadValuesChange,
  onGeneratePathway,
  generatePathwayPending,
  onCommit,
  commitPending,
}: Props) {
  const isDraft = !!selectedVersion && !selectedVersion.is_committed;
  const showGenerateForm = !versions?.length || !!selectedVersion?.is_committed;

  return (
    <>
      <div
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
          <h2 style={{ margin: 0, fontSize: 18 }}>{selectedPlan?.name ?? "Select a plan"}</h2>
          <p style={{ margin: "6px 0 0", color: theme.muted, fontSize: 13 }}>
            {selectedVersion
              ? `Version ${selectedVersion.version_number} · ${selectedVersion.is_committed ? "committed" : "draft"}`
              : "Choose a plan version to run."}
          </p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {isDraft && (
            <button
              type="button"
              onClick={onCommit}
              disabled={commitPending}
              style={{
                padding: "10px 14px",
                borderRadius: 10,
                border: 0,
                background: commitPending ? theme.mutedSoft : theme.text,
                color: "#fff",
                cursor: commitPending ? "not-allowed" : "pointer",
              }}
            >
              {commitPending ? "Committing..." : "Commit version"}
            </button>
          )}
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun || runPending}
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              border: 0,
              background: !canRun || runPending ? theme.mutedSoft : theme.text,
              color: "#fff",
              cursor: !canRun || runPending ? "not-allowed" : "pointer",
            }}
          >
            {runPending ? "Running..." : canRun ? "Run selected version" : "Commit version to run"}
          </button>
        </div>
      </div>

      {showGenerateForm && (
        <section style={{ ...pageCardStyle, padding: 18, display: "grid", gap: 10 }}>
          <h3 style={{ marginTop: 0, fontSize: 16 }}>Generate launch pathway</h3>
          <p style={{ margin: 0, color: theme.muted, fontSize: 13 }}>
            Point Cardre at a Parquet file, and it will generate the full canonical scorecard
            pathway as a draft version. If your target column differs from the default
            <code> credit_risk_class</code>, set it here — it is propagated to every step.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (selectedDataset && !datasetImportPending) onGeneratePathway();
            }}
            style={{ display: "grid", gap: 8 }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                gap: 8,
                alignItems: "center",
              }}
            >
              <div
                style={{
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: `1px solid ${theme.borderStrong}`,
                  background: theme.canvasSoft,
                  color: theme.muted,
                  fontSize: 13,
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {selectedDataset?.file_name ?? "No Parquet file selected"}
              </div>
              <div
                style={{
                  position: "relative",
                }}
              >
                <input
                  type="file"
                  accept=".parquet"
                  aria-label="Browse for Parquet file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) onDatasetFile(file);
                    event.currentTarget.value = "";
                  }}
                  disabled={datasetImportPending}
                  style={{
                    position: "absolute",
                    inset: 0,
                    zIndex: 1,
                    width: "100%",
                    height: "100%",
                    opacity: 0,
                    cursor: datasetImportPending ? "not-allowed" : "pointer",
                  }}
                  id="parquet-file-picker"
                />
                <div
                  aria-hidden="true"
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: 0,
                    background: datasetImportPending ? theme.mutedSoft : theme.text,
                    color: "#fff",
                    cursor: datasetImportPending ? "not-allowed" : "pointer",
                    whiteSpace: "nowrap",
                    opacity: datasetImportPending ? 0.6 : 1,
                    pointerEvents: "none",
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  Browse…
                </div>
              </div>
            </div>
            <div role="status" aria-live="polite" style={{ color: theme.muted, fontSize: 13 }}>
              {datasetImportPending
                ? `Importing ${datasetImportingName ?? "selected dataset"}…`
                : datasetImportError && selectedDataset
                  ? `Upload failed. Previous dataset still selected: ${selectedDataset.file_name}`
                  : selectedDataset
                    ? `Ready: ${selectedDataset.file_name}`
                    : "No dataset selected"}
            </div>
            {datasetImportError && (
              <div
                role="alert"
                style={{
                  color: theme.redText,
                  background: theme.redBg,
                  padding: 10,
                  borderRadius: 8,
                }}
              >
                Could not import the selected dataset: {datasetImportError}
                {selectedDataset && (
                  <> The previous dataset, {selectedDataset.file_name}, remains selected.</>
                )}
              </div>
            )}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: 8,
              }}
            >
              <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
                <span style={{ color: theme.muted }}>Target column</span>
                <input
                  type="text"
                  value={targetColumn}
                  onChange={(event) => onTargetColumnChange(event.target.value)}
                  placeholder="credit_risk_class"
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: `1px solid ${theme.borderStrong}`,
                    boxSizing: "border-box",
                  }}
                />
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
                <span style={{ color: theme.muted }}>Good values (comma-separated)</span>
                <input
                  type="text"
                  value={goodValues}
                  onChange={(event) => onGoodValuesChange(event.target.value)}
                  placeholder="good"
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: `1px solid ${theme.borderStrong}`,
                    boxSizing: "border-box",
                  }}
                />
              </label>
              <label style={{ display: "grid", gap: 4, fontSize: 12 }}>
                <span style={{ color: theme.muted }}>Bad values (comma-separated)</span>
                <input
                  type="text"
                  value={badValues}
                  onChange={(event) => onBadValuesChange(event.target.value)}
                  placeholder="bad"
                  style={{
                    padding: "10px 12px",
                    borderRadius: 10,
                    border: `1px solid ${theme.borderStrong}`,
                    boxSizing: "border-box",
                  }}
                />
              </label>
            </div>
            <button
              type="submit"
              disabled={!selectedDataset || datasetImportPending || generatePathwayPending}
              style={{
                padding: "10px 12px",
                borderRadius: 10,
                border: 0,
                background:
                  !selectedDataset || datasetImportPending || generatePathwayPending
                    ? theme.mutedSoft
                    : theme.text,
                color: "#fff",
                cursor:
                  !selectedDataset || datasetImportPending || generatePathwayPending
                    ? "not-allowed"
                    : "pointer",
              }}
            >
              {generatePathwayPending ? "Generating..." : "Generate launch pathway"}
            </button>
          </form>
        </section>
      )}

      <section style={{ ...pageCardStyle, padding: 18 }}>
        <h3 style={{ marginTop: 0, fontSize: 16 }}>Plan Versions</h3>
        {versionsLoading ? (
          <div style={{ color: theme.muted }}>Loading versions...</div>
        ) : versions?.length ? (
          <div style={{ display: "grid", gap: 10 }}>
            {versions
              .slice()
              .reverse()
              .map((version) => (
                <button
                  key={version.plan_version_id}
                  type="button"
                  onClick={() => onSelectVersion(version.plan_version_id)}
                  style={{
                    textAlign: "left",
                    padding: 12,
                    borderRadius: 12,
                    border: `1px solid ${version.plan_version_id === effectiveSelectedVersionId ? theme.text : theme.border}`,
                    background:
                      version.plan_version_id === effectiveSelectedVersionId
                        ? theme.canvasSoft
                        : theme.surface,
                    cursor: "pointer",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <strong>Version {version.version_number}</strong>
                    <span
                      style={{
                        color: version.is_committed ? theme.greenText : theme.yellowText,
                      }}
                    >
                      {version.is_committed ? "Committed" : "Draft"}
                    </span>
                  </div>
                  <div style={{ color: theme.muted, fontSize: 12, marginTop: 4 }}>
                    {version.description || version.plan_version_id}
                  </div>
                </button>
              ))}
          </div>
        ) : (
          <div style={{ color: theme.muted }}>No versions found.</div>
        )}
      </section>
    </>
  );
}
