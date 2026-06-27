import React from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { isApiError, formatApiError } from "../api/client";
import { theme } from "../styles";

interface QueryStateProps<T> {
  query: UseQueryResult<T>;
  loading?: React.ReactNode;
  error?: React.ReactNode | ((err: unknown) => React.ReactNode);
  children: (data: T) => React.ReactNode;
}

export function QueryState<T>({ query, loading, error, children }: QueryStateProps<T>) {
  if (query.isLoading) {
    return (
      <div style={{ padding: 24, color: theme.muted, fontSize: 13 }}>{loading ?? "Loading…"}</div>
    );
  }

  if (query.error) {
    const err = query.error;
    const msg = isApiError(err)
      ? formatApiError(err)
      : err instanceof Error
        ? err.message
        : String(err);
    const requestId = isApiError(err) ? err.requestId : undefined;
    return (
      <div style={{ padding: 24, color: theme.redText, fontSize: 13 }}>
        {error instanceof Function
          ? error(err)
          : (error ?? (
              <div>
                <div>{msg}</div>
                {requestId && (
                  <div style={{ fontSize: 11, marginTop: 4, color: theme.muted }}>
                    Request ID: {requestId}
                  </div>
                )}
                {query.refetch && (
                  <button
                    onClick={() => query.refetch()}
                    style={{
                      marginTop: 8,
                      padding: "4px 10px",
                      borderRadius: 4,
                      border: `1px solid ${theme.border}`,
                      fontSize: 12,
                      backgroundColor: theme.surface,
                      cursor: "pointer",
                      color: theme.text,
                    }}
                  >
                    Retry
                  </button>
                )}
              </div>
            ))}
      </div>
    );
  }

  if (!query.data) {
    return (
      <div style={{ padding: 24, color: theme.redText, fontSize: 13 }}>No data available.</div>
    );
  }

  return <>{children(query.data)}</>;
}
