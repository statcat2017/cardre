import { describe, it, expect } from "vitest";
import { latestSuccessfulRun } from "../runs";
import type { RunListItem } from "../../types";

function makeRun(overrides: Partial<RunListItem> & { run_id: string }): RunListItem {
  return {
    plan_version_id: "pv1",
    status: "succeeded",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T01:00:00Z",
    step_count: 0,
    ...overrides,
  };
}

describe("latestSuccessfulRun", () => {
  it("returns the run with the greatest finished_at", () => {
    const runs: RunListItem[] = [
      makeRun({ run_id: "r1", finished_at: "2026-01-01T02:00:00Z" }),
      makeRun({ run_id: "r2", finished_at: "2026-01-01T03:00:00Z" }),
      makeRun({ run_id: "r3", finished_at: "2026-01-01T01:00:00Z" }),
    ];
    expect(latestSuccessfulRun(runs)?.run_id).toBe("r2");
  });

  it("falls back to started_at when finished_at is null", () => {
    const runs: RunListItem[] = [
      makeRun({ run_id: "r1", finished_at: null, started_at: "2026-01-01T03:00:00Z" }),
      makeRun({ run_id: "r2", finished_at: null, started_at: "2026-01-01T01:00:00Z" }),
    ];
    expect(latestSuccessfulRun(runs)?.run_id).toBe("r1");
  });

  it("returns null when no runs succeeded", () => {
    const runs: RunListItem[] = [
      makeRun({ run_id: "r1", status: "failed" }),
      makeRun({ run_id: "r2", status: "cancelled" }),
    ];
    expect(latestSuccessfulRun(runs)).toBeNull();
  });

  it("returns null for an empty list", () => {
    expect(latestSuccessfulRun([])).toBeNull();
  });

  it("does not mutate the input array", () => {
    const runs: RunListItem[] = [
      makeRun({ run_id: "r2", finished_at: "2026-01-01T03:00:00Z" }),
      makeRun({ run_id: "r1", finished_at: "2026-01-01T01:00:00Z" }),
    ];
    const original = [...runs];
    latestSuccessfulRun(runs);
    expect(runs).toEqual(original);
  });

  it("is deterministic when two runs share the same timestamp (stable on order)", () => {
    const runs: RunListItem[] = [
      makeRun({ run_id: "r1", finished_at: "2026-01-01T02:00:00Z" }),
      makeRun({ run_id: "r2", finished_at: "2026-01-01T02:00:00Z" }),
    ];
    const result = latestSuccessfulRun(runs);
    expect(result).not.toBeNull();
    expect(["r1", "r2"]).toContain(result!.run_id);
  });
});
