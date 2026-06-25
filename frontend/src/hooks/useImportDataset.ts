import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";

const DEFAULT_IMPORT_PAYLOAD = {
  dataset_id: "",
  format: "auto" as const,
  has_header: true,
  schema_overrides: {} as Record<string, unknown>,
};

export function useImportDataset(onSuccess?: () => void, onError?: (e: Error) => void) {
  return useMutation({
    mutationFn: (body: { project_id: string; source_path: string }) =>
      api.importDataset({
        ...DEFAULT_IMPORT_PAYLOAD,
        ...body,
      }),
    onSuccess,
    onError,
  });
}
