import { useMemo } from "react";
import { formatApiError, type ApiError } from "../api/client";

export function useDiagnosticsPanel(
  diagnostics: string[],
  liveDiagnostic: string | null,
  error: string | null,
  lastPollError: ApiError | null,
  lastRunError: string | null,
  runStalled: boolean,
) {
  const messages = useMemo(() => {
    const msgs = [
      ...diagnostics,
      ...(liveDiagnostic ? [`  └ ${liveDiagnostic}`] : []),
      error ? `[error] ${error}` : null,
      lastPollError ? `[poll error] ${formatApiError(lastPollError)}` : null,
      lastRunError ? `[run error] ${lastRunError}` : null,
      runStalled ? "[stalled] Run stalled — no progress detected" : null,
    ].filter(Boolean) as string[];
    return msgs;
  }, [diagnostics, liveDiagnostic, error, lastPollError, lastRunError, runStalled]);

  return { diagnosticsMessages: messages };
}
