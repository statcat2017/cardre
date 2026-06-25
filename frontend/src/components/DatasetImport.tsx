import React from "react";
import { ImportDatasetForm } from "./ImportDatasetForm";

interface Props {
  projectId: string;
  onImported: () => void;
}

export function DatasetImport({ projectId, onImported }: Props) {
  return <ImportDatasetForm projectId={projectId} onImported={onImported} />;
}
