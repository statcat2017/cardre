import { describe, it, expect } from "vitest";
import { canonicalizeStepId } from "../stepDisplayMetadata";

describe("canonicalizeStepId", () => {
  it("strips __br_ suffix", () => {
    expect(canonicalizeStepId("manual-binning__br_abc123")).toBe("manual-binning");
  });

  it("leaves non-branch IDs unchanged", () => {
    expect(canonicalizeStepId("manual-binning")).toBe("manual-binning");
    expect(canonicalizeStepId("woe-transform-train")).toBe("woe-transform-train");
  });

  it("handles empty string", () => {
    expect(canonicalizeStepId("")).toBe("");
  });
});
