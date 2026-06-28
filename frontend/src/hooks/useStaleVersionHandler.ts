import { useCallback, useState } from "react";
import { isApiError } from "../api/client";

export function useStaleVersionHandler() {
  const [isStaleRefreshing, setIsStaleRefreshing] = useState(false);

  const isStaleVersion = useCallback((err: unknown): boolean => {
    if (!isApiError(err)) return false;
    return err.status === 409 && err.detail.code === "STALE_VERSION";
  }, []);

  const handleStaleVersion = useCallback(
    (err: unknown, onPlanRefreshed: (detail: { latest_version_id?: string }) => void): boolean => {
      if (!isStaleVersion(err)) return false;
      const latestId = isApiError(err)
        ? (err.detail.context?.latest_version_id as string | undefined)
        : undefined;
      setIsStaleRefreshing(true);
      onPlanRefreshed({ latest_version_id: latestId });
      setIsStaleRefreshing(false);
      return true;
    },
    [isStaleVersion],
  );

  return { isStaleVersion, handleStaleVersion, isStaleRefreshing };
}
