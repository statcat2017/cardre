import { isApiError, formatApiError } from "../api/client";
import { theme } from "../styles";

interface Props {
  error: unknown;
  context?: string;
}

export function ErrorNotice({ error, context }: Props) {
  if (!error) return null;
  const msg = isApiError(error)
    ? formatApiError(error)
    : error instanceof Error
      ? error.message
      : String(error);
  return (
    <div style={{ padding: "8px 12px", color: theme.redText, fontSize: 13 }}>
      {context && <div style={{ fontWeight: 600, marginBottom: 4 }}>{context}</div>}
      <div>{msg}</div>
    </div>
  );
}
