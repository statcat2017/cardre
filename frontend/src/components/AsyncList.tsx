import type { ReactNode } from "react";

import { theme } from "../styles";

interface AsyncListProps<T> {
  isLoading: boolean;
  items: T[] | undefined;
  renderItem: (item: T) => ReactNode;
  emptyText: string;
  loadingText?: string;
}

export function AsyncList<T>({
  isLoading,
  items,
  renderItem,
  emptyText,
  loadingText = "Loading...",
}: AsyncListProps<T>) {
  if (isLoading) {
    return <p style={{ margin: 0, color: theme.muted, fontSize: 14 }}>{loadingText}</p>;
  }
  if (!items?.length) {
    return <p style={{ margin: 0, color: theme.muted, fontSize: 14 }}>{emptyText}</p>;
  }
  return <>{items.map(renderItem)}</>;
}
