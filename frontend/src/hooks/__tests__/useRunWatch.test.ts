/**
 * Tests for useRunWatch hook (#217).
 *
 * Verifies that polling uses the typed API client (api.getRun) which
 * sends the project header, stops on terminal states, and reports
 * distinct transport-error states.
 */

import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useRunWatch } from "../useRunWatch";

function makeRun(status: string, runId = "run-1") {
  return {
    run_id: runId,
    plan_version_id: "pv-1",
    status,
    started_at: "2025-01-01T00:00:00",
    step_count: 0,
    executed_step_ids: [],
    diagnostics: [],
    is_stale: false,
  };
}

function mockFetchResponse(body: object, status = 200) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

describe("useRunWatch", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses api.getRun (typed client) to fetch runs", async () => {
    mockFetchResponse(makeRun("running"));

    const { result } = renderHook(() =>
      useRunWatch({
        projectId: "proj-1",
        runId: "run-1",
        pollIntervalMs: 100000,
      }),
    );

    await waitFor(() => expect(result.current.run).not.toBeNull(), {
      timeout: 3000,
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const callArgs = vi.mocked(fetch).mock.calls[0];
    const headers = callArgs[1]?.headers as Record<string, string>;
    expect(headers["X-Project-Id"]).toBe("proj-1");
  });

  it("stops polling on succeeded", async () => {
    mockFetchResponse(makeRun("succeeded"));

    const { result } = renderHook(() =>
      useRunWatch({
        projectId: "proj-1",
        runId: "run-1",
        pollIntervalMs: 100000,
      }),
    );

    await waitFor(() => expect(result.current.status).toBe("succeeded"), {
      timeout: 3000,
    });
    expect(result.current.polling).toBe(false);
  });

  it("stops polling on failed", async () => {
    mockFetchResponse(makeRun("failed"));

    const { result } = renderHook(() =>
      useRunWatch({
        projectId: "proj-1",
        runId: "run-1",
        pollIntervalMs: 100000,
      }),
    );

    await waitFor(() => expect(result.current.status).toBe("failed"), {
      timeout: 3000,
    });
    expect(result.current.polling).toBe(false);
  });

  it("reports sidecar_unreachable distinctly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));

    const { result } = renderHook(() =>
      useRunWatch({
        projectId: "proj-1",
        runId: "run-1",
        pollIntervalMs: 100000,
        maxErrorRetries: 1,
      }),
    );

    await waitFor(() => expect(result.current.status).not.toBe("loading"), {
      timeout: 3000,
    });
    // The specific transport error status is preserved as the final state.
    expect(result.current.status).toBe("sidecar_unreachable");
  });
});
