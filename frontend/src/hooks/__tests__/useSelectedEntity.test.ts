import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSelectedEntity } from "../useSelectedEntity";

const items = [
  { id: "a", name: "A" },
  { id: "b", name: "B" },
  { id: "c", name: "C" },
];

describe("useSelectedEntity", () => {
  it("returns null when items are undefined", () => {
    const { result } = renderHook(() => useSelectedEntity("a", undefined, "id", "first"));
    expect(result.current).toBeNull();
  });

  it("returns null when items are null", () => {
    const { result } = renderHook(() => useSelectedEntity("a", null, "id", "first"));
    expect(result.current).toBeNull();
  });

  it("returns null when there are no items", () => {
    const { result } = renderHook(() => useSelectedEntity("a", [], "id", "first"));
    expect(result.current).toBeNull();
  });

  it("keeps the selected id when it still exists in the items", () => {
    const { result } = renderHook(() => useSelectedEntity("b", items, "id", "first"));
    expect(result.current).toBe("b");
  });

  it("falls back to the first item when the selection is stale", () => {
    const { result } = renderHook(() => useSelectedEntity("stale", items, "id", "first"));
    expect(result.current).toBe("a");
  });

  it("falls back to the last item when the strategy is last", () => {
    const { result } = renderHook(() => useSelectedEntity("stale", items, "id", "last"));
    expect(result.current).toBe("c");
  });

  it("falls back to the last item when the selection is null and strategy is last", () => {
    const { result } = renderHook(() => useSelectedEntity(null, items, "id", "last"));
    expect(result.current).toBe("c");
  });

  it("returns null when the fallback id field value is not a string", () => {
    const numericItems = [{ id: 1, name: "A" }];
    const { result } = renderHook(() => useSelectedEntity(null, numericItems, "id", "first"));
    expect(result.current).toBeNull();
  });

  it("recomputes when items change", () => {
    const { result, rerender } = renderHook(
      ({ currentItems }) => useSelectedEntity("b", currentItems, "id", "first"),
      { initialProps: { currentItems: items } },
    );
    expect(result.current).toBe("b");

    rerender({ currentItems: [{ id: "x", name: "X" }] });
    expect(result.current).toBe("x");
  });
});
