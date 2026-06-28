import { describe, it, expect, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useStaleVersionHandler } from "../useStaleVersionHandler";
import { ApiError } from "../../api/client";

describe("useStaleVersionHandler", () => {
  it("returns isStaleRefreshing=false initially", () => {
    const { result } = renderHook(() => useStaleVersionHandler());
    expect(result.current.isStaleRefreshing).toBe(false);
  });

  it("calls onPlanRefreshed with latest_version_id when error is 409 STALE_VERSION", () => {
    const onPlanRefreshed = vi.fn();
    const { result } = renderHook(() => useStaleVersionHandler());

    const err = new ApiError(409, {
      code: "STALE_VERSION",
      message: "Version is stale",
      context: { latest_version_id: "v2" },
    });

    act(() => {
      result.current.handleStaleVersion(err, onPlanRefreshed);
    });

    expect(onPlanRefreshed).toHaveBeenCalledWith({ latest_version_id: "v2" });
  });

  it("returns true for isStaleVersion when matched", () => {
    const { result } = renderHook(() => useStaleVersionHandler());

    const err = new ApiError(409, {
      code: "STALE_VERSION",
      message: "Version is stale",
    });

    expect(result.current.isStaleVersion(err)).toBe(true);
  });

  it("returns false for isStaleVersion when not matched", () => {
    const { result } = renderHook(() => useStaleVersionHandler());

    const err = new ApiError(500, {
      code: "RUN_EXECUTION_FAILED",
      message: "Execution failed",
    });

    expect(result.current.isStaleVersion(err)).toBe(false);
  });

  it("does not call onPlanRefreshed for non-stale errors", () => {
    const onPlanRefreshed = vi.fn();
    const { result } = renderHook(() => useStaleVersionHandler());

    const err = new ApiError(500, {
      code: "RUN_EXECUTION_FAILED",
      message: "Execution failed",
    });

    const returned = result.current.handleStaleVersion(err, onPlanRefreshed);
    expect(onPlanRefreshed).not.toHaveBeenCalled();
    expect(returned).toBe(false);
  });
});
