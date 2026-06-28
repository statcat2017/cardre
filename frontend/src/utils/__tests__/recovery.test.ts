import { describe, it, expect } from "vitest";
import { ApiError } from "../../api/client";
import { classifyError } from "../errors";

describe("classifyError", () => {
  it("returns fatal for non-ApiError", () => {
    const result = classifyError(new Error("generic"));
    expect(result.kind).toBe("fatal");
    expect(result.retryable).toBe(false);
  });

  it("returns developer_fixable for SIDECAR_UNREACHABLE", () => {
    const err = new ApiError(0, {
      code: "SIDECAR_UNREACHABLE",
      message: "Could not reach sidecar",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("developer_fixable");
    expect(result.retryable).toBe(true);
    expect(result.title).toBeTruthy();
    expect(result.message).toBeTruthy();
    expect(result.requestId).toBe(err.requestId);
  });

  it("returns retryable for REQUEST_TIMEOUT", () => {
    const err = new ApiError(0, {
      code: "REQUEST_TIMEOUT",
      message: "timed out",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("retryable");
    expect(result.retryable).toBe(true);
  });

  it("returns user_fixable for PLAN_CONTAINS_UNAVAILABLE_NODES", () => {
    const err = new ApiError(400, {
      code: "PLAN_CONTAINS_UNAVAILABLE_NODES",
      message: "Plan has unavailable nodes",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("user_fixable");
    expect(result.retryable).toBe(false);
  });

  it("returns user_fixable for OPTIONAL_DEPENDENCY_NOT_INSTALLED", () => {
    const err = new ApiError(400, {
      code: "OPTIONAL_DEPENDENCY_NOT_INSTALLED",
      message: "Missing dep",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("user_fixable");
    expect(result.retryable).toBe(false);
  });

  it("returns developer_fixable for GOVERNANCE_NOT_ENABLED", () => {
    const err = new ApiError(403, {
      code: "GOVERNANCE_NOT_ENABLED",
      message: "Governance off",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("developer_fixable");
  });

  it("returns user_fixable for ARTIFACT_NOT_FOUND", () => {
    const err = new ApiError(404, {
      code: "ARTIFACT_NOT_FOUND",
      message: "Not found",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("user_fixable");
    expect(result.retryable).toBe(true);
  });

  it("returns retryable for RUN_DISPATCH_FAILED", () => {
    const err = new ApiError(500, {
      code: "RUN_DISPATCH_FAILED",
      message: "Dispatch failed",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("retryable");
    expect(result.retryable).toBe(true);
  });

  it("returns retryable for RUN_EXECUTION_FAILED", () => {
    const err = new ApiError(500, {
      code: "RUN_EXECUTION_FAILED",
      message: "Execution failed",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("retryable");
    expect(result.retryable).toBe(true);
  });

  it("falls back to fatal for unknown codes", () => {
    const err = new ApiError(500, {
      code: "SOME_UNKNOWN_CODE",
      message: "???",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("fatal");
  });

  it("propagates recoverable from backend detail", () => {
    const err = new ApiError(500, {
      code: "SOME_CODE",
      message: "msg",
      recoverable: true,
      severity: "error",
    });
    const result = classifyError(err);
    expect(result.kind).toBe("retryable");
    expect(result.retryable).toBe(true);
  });

  it("propagates error_id and request_id from detail", () => {
    const err = new ApiError(500, { code: "SOME_CODE", message: "msg", error_id: "err_xxx" }, { requestId: "req_yyy" });
    const result = classifyError(err);
    expect(result.requestId).toBe("req_yyy");
    expect(result.errorId).toBe("err_xxx");
  });
});
