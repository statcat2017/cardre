/**
 * React hook for loading and submitting manual-binning review state.
 */

import { useCallback, useState } from "react";
import { fetchJson, ApiError } from "../api/client";
import type { components } from "../api/schema.d";

export interface UseManualBinningReviewOptions {
  baseUrl: string;
  projectId: string;
}

export interface UseManualBinningReviewReturn {
  /** Currently loaded review, or null. */
  review: components["schemas"]["ManualBinningReviewResponse"] | null;
  /** Loading flag. */
  loading: boolean;
  /** Error string, if any. */
  error: string | null;
  /** Load a review by ID. */
  loadReview: (reviewId: string) => Promise<void>;
  /** Submit an atomic manual-binning edit (creates draft + review). */
  submitEdit: (request: components["schemas"]["ManualBinningEditRequest"]) => Promise<components["schemas"]["ManualBinningEditResponse"]>;
  /** Update an existing review (status, notes). */
  updateReview: (reviewId: string, update: components["schemas"]["ManualBinningReviewUpdate"]) => Promise<void>;
  /** Clear error state. */
  clearError: () => void;
}

export function useManualBinningReview(
  options: UseManualBinningReviewOptions,
): UseManualBinningReviewReturn {
  const { baseUrl, projectId } = options;
  const [review, setReview] = useState<components["schemas"]["ManualBinningReviewResponse"] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleError = useCallback((err: unknown) => {
    if (err instanceof ApiError) {
      setError(err.detail);
    } else if (err instanceof Error) {
      setError(err.message);
    } else {
      setError(String(err));
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const loadReview = useCallback(
    async (reviewId: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchJson<components["schemas"]["ManualBinningReviewResponse"]>(
          `${baseUrl}/projects/${projectId}/manual-binning/reviews/${reviewId}`,
        );
        setReview(data);
      } catch (err) {
        handleError(err);
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, projectId, handleError],
  );

  const submitEdit = useCallback(
    async (request: components["schemas"]["ManualBinningEditRequest"]): Promise<components["schemas"]["ManualBinningEditResponse"]> => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchJson<components["schemas"]["ManualBinningEditResponse"]>(
          `${baseUrl}/projects/${projectId}/manual-binning/edit`,
          {
            method: "POST",
            body: request,
          },
        );
        return data;
      } catch (err) {
        handleError(err);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, projectId, handleError],
  );

  const updateReview = useCallback(
    async (reviewId: string, update: components["schemas"]["ManualBinningReviewUpdate"]) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchJson<components["schemas"]["ManualBinningReviewResponse"]>(
          `${baseUrl}/projects/${projectId}/manual-binning/reviews/${reviewId}`,
          {
            method: "PATCH",
            body: update,
          },
        );
        setReview(data);
      } catch (err) {
        handleError(err);
      } finally {
        setLoading(false);
      }
    },
    [baseUrl, projectId, handleError],
  );

  return {
    review,
    loading,
    error,
    loadReview,
    submitEdit,
    updateReview,
    clearError,
  };
}
