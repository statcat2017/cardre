import { isApiError } from "../api/client";

export interface RenderableError {
  code: string;
  message: string;
  context?: Record<string, unknown>;
  diagnostics?: Array<{ code: string; message: string }>;
}

export function renderApiError(err: unknown): RenderableError | null {
  if (!isApiError(err)) return null;
  return {
    code: err.detail.code,
    message: err.detail.message,
    context: err.detail.context,
    diagnostics: err.detail.diagnostics,
  };
}
