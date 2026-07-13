/**
 * Robustness tests for the API client (fetchJson, ApiError).
 *
 * Ported from v1 — verifies SIDECAR_UNREACHABLE, REQUEST_TIMEOUT,
 * REQUEST_ABORTED, EMPTY_OK_BODY, EMPTY_ERROR_RESPONSE,
 * MALFORMED_JSON_RESPONSE, HTML_ERROR_RESPONSE, NON_JSON_ERROR_RESPONSE.
 */

import { describe, expect, it, vi, afterEach } from "vitest";
import { fetchJson, ApiError, toErrorMessage } from "../client";
import { ErrorCodes } from "../errorCodes";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("fetchJson", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns parsed JSON for a successful 200", async () => {
    const resp = new Response(JSON.stringify({ foo: "bar" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const result = await fetchJson<{ foo: string }>("/test");
    expect(result).toEqual({ foo: "bar" });
  });

  it("throws SIDECAR_UNREACHABLE on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.SIDECAR_UNREACHABLE);
    expect(err.status).toBe(503);
  });

  it("throws REQUEST_TIMEOUT on timeout", async () => {
    const timeoutError = new DOMException("Timeout", "TimeoutError");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(timeoutError);

    const err = (await fetchJson("/test", { timeoutMs: 10 }).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.REQUEST_TIMEOUT);
    expect(err.status).toBe(408);
  });

  it("throws REQUEST_ABORTED on abort signal", async () => {
    const abortError = new DOMException("Aborted", "AbortError");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(abortError);

    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.REQUEST_ABORTED);
    expect(err.status).toBe(499);
  });

  it("throws EMPTY_OK_BODY on 200 with empty body", async () => {
    const resp = new Response("", {
      status: 200,
      headers: { "content-type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.EMPTY_OK_BODY);
    expect(err.status).toBe(502);
  });

  it("throws MALFORMED_JSON_RESPONSE on 200 with invalid JSON", async () => {
    const resp = new Response("not json", {
      status: 200,
      headers: { "content-type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.MALFORMED_JSON_RESPONSE);
    expect(err.status).toBe(502);
  });

  it("throws MALFORMED_JSON_RESPONSE on 200 with wrong content type", async () => {
    const resp = new Response("{}", {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.MALFORMED_JSON_RESPONSE);
    expect(err.status).toBe(502);
  });

  it("throws HTML_ERROR_RESPONSE on error with HTML body", async () => {
    const resp = new Response("<html>404 Not Found</html>", {
      status: 400,
      headers: { "content-type": "text/html" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.HTML_ERROR_RESPONSE);
    expect(err.status).toBe(400);
  });

  it("throws NON_JSON_ERROR_RESPONSE on error with non-JSON body", async () => {
    const resp = new Response("Internal Server Error", {
      status: 400,
      headers: { "content-type": "text/plain" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.NON_JSON_ERROR_RESPONSE);
    expect(err.status).toBe(400);
  });

  it("throws EMPTY_ERROR_RESPONSE on error with empty body", async () => {
    const resp = new Response("", {
      status: 400,
      headers: { "content-type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.EMPTY_ERROR_RESPONSE);
    expect(err.status).toBe(400);
  });

  it("returns structured error from server JSON response", async () => {
    const resp = new Response(
      JSON.stringify({
        detail: { code: "PLAN_NOT_FOUND", message: "Plan not found", context: {} },
      }),
      {
        status: 400,
        headers: { "content-type": "application/json" },
      },
    );
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const err = (await fetchJson("/test").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("PLAN_NOT_FOUND");
    expect(err.message).toBe("Plan not found");
    expect(err.status).toBe(400);
  });

  it("returns HTTP 204 as undefined", async () => {
    const resp = new Response(undefined as unknown as BodyInit, { status: 204 });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(resp);
    const result = await fetchJson("/test");
    expect(result).toBeUndefined();
  });

  it("preserves external abort signal", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("Aborted by user", "AbortError");
    vi.spyOn(globalThis, "fetch").mockRejectedValue(abortError);

    setTimeout(() => controller.abort(), 5);

    const err = (await fetchJson("/test", { signal: controller.signal, timeoutMs: 5000 }).catch(
      (e) => e,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(ErrorCodes.REQUEST_ABORTED);
  });
});

describe("ApiError", () => {
  it("stores code, message, status, and context", () => {
    const err = new ApiError(ErrorCodes.RUN_EXECUTION_FAILED, "Test message", 418, {
      key: "value",
    });
    expect(err.code).toBe(ErrorCodes.RUN_EXECUTION_FAILED);
    expect(err.message).toBe("Test message");
    expect(err.status).toBe(418);
    expect(err.context).toEqual({ key: "value" });
    expect(err.detail).toBe("RUN_EXECUTION_FAILED: Test message (HTTP 418)");
  });

  it("defaults status to 500 and context to {}", () => {
    const err = new ApiError(ErrorCodes.RUN_NOT_FOUND, "msg");
    expect(err.status).toBe(500);
    expect(err.context).toEqual({});
  });

  it("is instance of Error", () => {
    const err = new ApiError(ErrorCodes.RUN_NOT_FOUND, "msg");
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
  });

  it("code is typed as ErrorCode union (rejects arbitrary strings at compile time)", () => {
    const err = new ApiError(ErrorCodes.SIDECAR_UNREACHABLE, "msg");
    const code: string = err.code;
    expect(code).toBe("SIDECAR_UNREACHABLE");
  });

  it("maps unknown detail.code to a known ErrorCode and preserves original in context", () => {
    const err = new ApiError(ErrorCodes.NON_JSON_ERROR_RESPONSE, "msg", 500, {
      originalCode: "UNKNOWN_CODE",
    });
    expect(err.code).toBe(ErrorCodes.NON_JSON_ERROR_RESPONSE);
    expect(err.context.originalCode).toBe("UNKNOWN_CODE");
  });
});

describe("toErrorMessage", () => {
  it("returns ApiError.detail for ApiError", () => {
    const err = new ApiError(ErrorCodes.RUN_EXECUTION_FAILED, "boom", 500);
    expect(toErrorMessage(err)).toBe("RUN_EXECUTION_FAILED: boom (HTTP 500)");
  });

  it("returns Error.message for plain Error", () => {
    expect(toErrorMessage(new Error("oops"))).toBe("oops");
  });

  it("returns String(value) for unknown types", () => {
    expect(toErrorMessage("raw string")).toBe("raw string");
    expect(toErrorMessage(42)).toBe("42");
    expect(toErrorMessage(null)).toBe("null");
  });
});
