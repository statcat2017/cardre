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
  sourcePath: string | null;
  onSourcePathChange: (path: string) => void;
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
  sourcePath,
  onSourcePathChange,
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
            Point Cardre at a CSV, and it will generate the full canonical scorecard pathway as a
            draft version.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (sourcePath?.trim()) onGeneratePathway();
            }}
            style={{ display: "grid", gap: 8 }}
          >
            <label
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                gap: 8,
                alignItems: "center",
              }}
            >
              <input
                type="text"
                value={sourcePath ?? ""}
                onChange={(event) => onSourcePathChange(event.target.value)}
                placeholder="Absolute path to your CSV"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: `1px solid ${theme.borderStrong}`,
                  boxSizing: "border-box",
                }}
              />
              <input
                type="file"
                accept=".csv,.parquet"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  const path = (file as unknown as { path?: string } | null)?.path;
                  if (path) onSourcePathChange(path);
                }}
                style={{ display: "none" }}
                id="csv-file-picker"
              />
              <label
                htmlFor="csv-file-picker"
                style={{
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: `1px solid ${theme.borderStrong}`,
                  background: theme.canvasSoft,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                Browse…
              </label>
            </label>
            <button
              type="submit"
              disabled={!sourcePath?.trim() || generatePathwayPending}
              style={{
                padding: "10px 12px",
                borderRadius: 10,
                border: 0,
                background:
                  !sourcePath?.trim() || generatePathwayPending ? theme.mutedSoft : theme.text,
                color: "#fff",
                cursor: !sourcePath?.trim() || generatePathwayPending ? "not-allowed" : "pointer",
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
