import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "../../api/client";
import { RecoveryBanner } from "../RecoveryBanner";

describe("RecoveryBanner", () => {
  it("renders nothing when error is null", () => {
    const { container } = render(<RecoveryBanner error={null} />);
    expect(container.textContent).toBe("");
  });

  it("renders error for non-ApiError", () => {
    render(<RecoveryBanner error={new Error("something broke")} />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("something broke")).toBeInTheDocument();
  });

  it("renders SIDECAR_UNREACHABLE with developer_fixable copy", () => {
    const err = new ApiError(0, {
      code: "SIDECAR_UNREACHABLE",
      message: "Could not reach the Cardre sidecar.",
    });
    render(<RecoveryBanner error={err} />);
    expect(screen.getByText("Can't reach the Cardre engine")).toBeInTheDocument();
    expect(
      screen.getByText(/The sidecar service is not running/),
    ).toBeInTheDocument();
  });

  it("renders ARTIFACT_NOT_FOUND with user_fixable copy", () => {
    const err = new ApiError(404, {
      code: "ARTIFACT_NOT_FOUND",
      message: "No artifact found",
    });
    render(<RecoveryBanner error={err} />);
    expect(screen.getByText("Artifact not found")).toBeInTheDocument();
  });

  it("shows retry button when retryable and onRetry provided", () => {
    const onRetry = vi.fn();
    const err = new ApiError(0, {
      code: "SIDECAR_UNREACHABLE",
      message: "Down",
    });
    render(<RecoveryBanner error={err} onRetry={onRetry} />);
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("does not show retry button when not retryable", () => {
    const err = new ApiError(403, {
      code: "GOVERNANCE_NOT_ENABLED",
      message: "Governance off",
    });
    render(<RecoveryBanner error={err} onRetry={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("calls onRetry when retry button clicked", async () => {
    const onRetry = vi.fn();
    const err = new ApiError(0, {
      code: "SIDECAR_UNREACHABLE",
      message: "Down",
    });
    render(<RecoveryBanner error={err} onRetry={onRetry} />);
    await userEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows request_id when available", () => {
    const err = new ApiError(0, { code: "SIDECAR_UNREACHABLE", message: "Down" }, { requestId: "req_abc123" });
    render(<RecoveryBanner error={err} />);
    expect(screen.getByText(/req_abc/)).toBeInTheDocument();
  });

  it("shows error_id when available", () => {
    const err = new ApiError(500, { code: "RUN_EXECUTION_FAILED", message: "Failed", error_id: "err_xyz" });
    render(<RecoveryBanner error={err} />);
    expect(screen.getByText(/err_xyz/)).toBeInTheDocument();
  });

  it("renders severity colour for fatal errors (red background)", () => {
    const err = new Error("fatal");
    render(<RecoveryBanner error={err} />);
    const banner = screen.getByText("Something went wrong").closest("div");
    const style = banner?.parentElement?.getAttribute("style") ?? "";
    expect(style).toContain("background");
  });

  it("renders with given style overrides", () => {
    const err = new Error("test");
    const { container } = render(<RecoveryBanner error={err} style={{ marginTop: 42 }} />);
    expect(container.firstElementChild?.getAttribute("style")).toContain("margin-top");
  });
});
