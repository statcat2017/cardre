import type { RunListItem } from "../types";

export function latestSuccessfulRun(runs: RunListItem[]): RunListItem | null {
  return (
    [...runs]
      .filter((r) => r.status === "succeeded")
      .sort((a, b) => {
        const aTime = Date.parse(a.finished_at ?? a.started_at ?? "");
        const bTime = Date.parse(b.finished_at ?? b.started_at ?? "");
        return bTime - aTime;
      })[0] ?? null
  );
}
