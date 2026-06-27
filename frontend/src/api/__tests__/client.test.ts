import { describe, it, expect, vi, afterEach } from "vitest";
import { api, ApiError, isApiError, formatApiError, getBaseUrl, fetchJson } from "../client";

function mockFetchResponse(status: number, body: string, headers?: Record<string, string>) {
  return vi.spyOn(global, "fetch").mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: new Map(Object.entries(headers ?? {})) as unknown as Headers,
    text: () => Promise.resolve(body),
    json: () => {
      try {
        return Promise.resolve(JSON.parse(body));
      } catch {
        return Promise.reject(new Error("Invalid JSON"));
      }
    },
  } as Response);
}

function mockFetchNeverResolves() {
  return vi.spyOn(global, "fetch").mockImplementation((_url, init) => {
    const signal = (init as RequestInit)?.signal;
    return new Promise<Response>((_resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException("The operation was aborted", "AbortError"));
        return;
      }
      signal?.addEventListener(
        "abort",
        () => {
          reject(new DOMException("The operation was aborted", "AbortError"));
        },
        { once: true },
      );
    });
  });
}

function mockFetchError(error: Error) {
  return vi.spyOn(global, "fetch").mockRejectedValue(error);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchJson timeout", () => {
  it(
    "throws REQUEST_TIMEOUT when fetch never resolves within timeoutMs",
    { timeout: 10_000 },
    async () => {
      mockFetchNeverResolves();
      // Use a custom call with a very short timeout to avoid waiting 5s
      const promise = api.health();
      await expect(promise).rejects.toThrow(ApiError);
      await expect(promise).rejects.toMatchObject({
        code: "REQUEST_TIMEOUT",
        status: 0,
      });
    },
  );

  it("aborts the underlying request on timeout", { timeout: 10_000 }, async () => {
    const spy = mockFetchNeverResolves();
    const promise = api.health();
    await expect(promise).rejects.toThrow();
    const init = spy.mock.calls[0][1] as RequestInit;
    expect(init?.signal).toBeDefined();
    expect(init!.signal!.aborted).toBe(true);
  });
});

describe("fetchJson abort", () => {
  it(
    "throws REQUEST_ABORTED when caller signal aborts before fetch",
    { timeout: 10_000 },
    async () => {
      const controller = new AbortController();
      controller.abort();
      // Mock that checks the signal — if already aborted, reject immediately
      vi.spyOn(global, "fetch").mockImplementation((_url, init) => {
        const signal = (init as RequestInit)?.signal;
        if (signal?.aborted) {
          return Promise.reject(new DOMException("The operation was aborted", "AbortError"));
        }
        return new Promise<Response>(() => {});
      });
      const promise = fetchJson("/health", { signal: controller.signal, timeoutMs: 10_000 });
      await expect(promise).rejects.toThrow(ApiError);
      await expect(promise).rejects.toMatchObject({
        code: "REQUEST_ABORTED",
        status: 0,
      });
    },
  );
});

describe("fetchJson malformed response", () => {
  it("throws MALFORMED_JSON_RESPONSE on 200 with invalid JSON", async () => {
    mockFetchResponse(200, "not json at all");
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "MALFORMED_JSON_RESPONSE",
      status: 200,
    });
  });

  it("includes rawBodyPreview on malformed response", async () => {
    mockFetchResponse(200, "not json at all");
    try {
      await api.health();
    } catch (e: unknown) {
      if (isApiError(e)) {
        expect(e.rawBodyPreview).toBe("not json at all");
      }
    }
  });
});

describe("fetchJson response-body timeout", () => {
  it("throws REQUEST_TIMEOUT when headers arrive but body never resolves", async () => {
    vi.useRealTimers();
    vi.spyOn(global, "fetch").mockImplementation((_url, init) => {
      const signal = (init as RequestInit)?.signal;
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map() as unknown as Headers,
        text: () =>
          new Promise<string>((resolve, reject) => {
            if (signal?.aborted) {
              reject(new DOMException("The operation was aborted", "AbortError"));
              return;
            }
            signal?.addEventListener(
              "abort",
              () => {
                reject(new DOMException("The operation was aborted", "AbortError"));
              },
              { once: true },
            );
          }),
      } as unknown as Response);
    });
    const promise = fetchJson("/health", { timeoutMs: 50 });
    await expect(promise).rejects.toMatchObject({ code: "REQUEST_TIMEOUT" });
  });
});

describe("fetchJson outbound request ID", () => {
  it("sends X-Cardre-Request-Id header on every request", { timeout: 10_000 }, async () => {
    const spy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Map() as unknown as Headers,
      text: () => Promise.resolve(JSON.stringify({ status: "ok" })),
    } as Response);
    await api.health();
    const headers = spy.mock.calls[0][1]?.headers as Record<string, string> | undefined;
    expect(headers?.["X-Cardre-Request-Id"]).toBeDefined();
    expect(typeof headers!["X-Cardre-Request-Id"]).toBe("string");
    expect(headers!["X-Cardre-Request-Id"].length).toBeGreaterThan(0);
  });

  it("falls back to outbound request ID when no response header", { timeout: 10_000 }, async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Map() as unknown as Headers,
      text: () => Promise.resolve(""),
    } as Response);
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "EMPTY_ERROR_RESPONSE",
    });
    try {
      await promise;
    } catch (e: unknown) {
      if (e instanceof ApiError) {
        expect(e.requestId).toBeDefined();
        expect(e.requestId!.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("fetchJson empty body", () => {
  it("throws EMPTY_OK_BODY on 200 with empty body by default", async () => {
    mockFetchResponse(200, "");
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "EMPTY_OK_BODY",
      status: 200,
    });
  });
});

describe("fetchJson HTML error", () => {
  it("throws HTML_ERROR_RESPONSE on 502 with HTML body", async () => {
    mockFetchResponse(502, "<html><body>Server Error</body></html>");
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "HTML_ERROR_RESPONSE",
      status: 502,
    });
  });
});

describe("fetchJson unreachable", () => {
  it("throws SIDECAR_UNREACHABLE when fetch rejects", async () => {
    mockFetchError(new TypeError("Failed to fetch"));
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "SIDECAR_UNREACHABLE",
      status: 0,
    });
  });
});

describe("fetchJson server error with code", () => {
  it("throws ApiError with server code and requestId", async () => {
    mockFetchResponse(
      500,
      JSON.stringify({
        detail: { code: "RUN_EXECUTION_FAILED", message: "Something broke" },
      }),
      { "X-Cardre-Request-Id": "req_abc123" },
    );
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "RUN_EXECUTION_FAILED",
      status: 500,
      requestId: "req_abc123",
    });
  });
});

describe("fetchJson empty error body", () => {
  it("throws EMPTY_ERROR_RESPONSE on 500 with empty body", async () => {
    mockFetchResponse(500, "");
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "EMPTY_ERROR_RESPONSE",
      status: 500,
    });
  });
});

describe("fetchJson non-JSON error body", () => {
  it("throws NON_JSON_ERROR_RESPONSE on 500 with plain text", async () => {
    mockFetchResponse(500, "Internal Server Error");
    const promise = api.health();
    await expect(promise).rejects.toThrow(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "NON_JSON_ERROR_RESPONSE",
      status: 500,
    });
  });
});

describe("formatApiError", () => {
  it("formats ApiError with code and message", () => {
    const err = new ApiError(0, {
      code: "SIDECAR_UNREACHABLE",
      message: "Could not reach the Cardre sidecar.",
    });
    expect(formatApiError(err)).toBe("SIDECAR_UNREACHABLE: Could not reach the Cardre sidecar.");
  });

  it("includes requestId when present", () => {
    const err = new ApiError(
      500,
      {
        code: "RUN_EXECUTION_FAILED",
        message: "Something broke",
      },
      { requestId: "req_abc123" },
    );
    expect(formatApiError(err)).toContain("req=req_abc1");
  });

  it("includes timeout when present", () => {
    const err = new ApiError(
      0,
      {
        code: "REQUEST_TIMEOUT",
        message: "Request timed out after 5000ms.",
      },
      { timedOutAtMs: 5000 },
    );
    expect(formatApiError(err)).toContain("timeout=5000ms");
  });

  it("falls back to Error.message for plain errors", () => {
    expect(formatApiError(new Error("boom"))).toBe("boom");
  });

  it("stringifies non-Error values", () => {
    expect(formatApiError("oops")).toBe("oops");
  });
});

describe("getBaseUrl", () => {
  it("defaults to localhost:8752", () => {
    expect(getBaseUrl()).toBe("http://127.0.0.1:8752");
  });
});
