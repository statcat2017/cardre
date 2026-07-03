import { useMemo } from "react";

/**
 * Validates a user selection against API data and falls back to first/last item.
 *
 * @param selectedId - The user's currently selected ID (may be stale).
 * @param items - Array of entities returned by the API (may be null/undefined while loading).
 * @param idField - The property name that holds the identifier on each item.
 * @param strategy - Pick `"first"` or `"last"` item when the selection is invalid.
 * @returns A valid entity ID, or `null` when no items exist.
 */
export function useSelectedEntity<T extends Record<string, unknown>>(
  selectedId: string | null,
  items: T[] | null | undefined,
  idField: keyof T,
  strategy: "first" | "last",
): string | null {
  return useMemo(() => {
    if (!items || items.length === 0) return null;

    if (selectedId && items.some((item) => item[idField] === selectedId)) {
      return selectedId;
    }

    const index = strategy === "last" ? items.length - 1 : 0;
    const fallback = items[index]?.[idField];
    return typeof fallback === "string" ? fallback : null;
  }, [selectedId, items, idField, strategy]);
}
