import { theme, pageCardStyle } from "../styles";

interface Version {
  plan_version_id: string;
  version_number: number;
  is_committed: boolean;
  description?: string | null;
}

interface SelectedPlan {
  plan_id: string;
  name: string;
}

interface SelectedVersion {
  plan_version_id: string;
  version_number: number;
  is_committed: boolean;
}

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
}: Props) {
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
