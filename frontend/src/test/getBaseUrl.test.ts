import { describe, it, expect } from "vitest";

describe("getBaseUrl", () => {
  it("defaults to localhost:8752", async () => {
    const mod = await import("../api/client");
    expect(mod.getBaseUrl()).toBe("http://127.0.0.1:8752");
  });
});
