import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { ManualBinningEditDialog } from "../ManualBinningEditDialog";
import { buildManualBinningEditorState } from "../../test/fixtures/manualBinning";

const PLAN_ID = "plan1";
const STEP_ID = "manual-binning";
const PROJECT_ID = "prj1";
const BASE_PV = "pv1";

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const state = buildManualBinningEditorState();
  const onClose = vi.fn();
  const onSaved = vi.fn();
  return {
    ...render(<QueryClientProvider client={qc}><ManualBinningEditDialog
      variable="income"
      state={state}
      planId={PLAN_ID}
      basePlanVersionId={BASE_PV}
      stepId={STEP_ID}
      projectId={PROJECT_ID}
      onClose={onClose}
      onSaved={onSaved}
    /></QueryClientProvider>),
    onClose, onSaved,
  };
}

async function fillReason(user: ReturnType<typeof userEvent.setup>, action = "merge_bins") {
  // Set reason text
  const textarea = screen.getByPlaceholderText("Describe why this edit is needed…");
  await user.type(textarea, "Test merge.");
  // Set reason code (second combobox)
  const selects = screen.getAllByRole("combobox");
  const reasonSelect = selects[selects.length - 1]; // last combobox = reason code
  await user.selectOptions(reasonSelect, "monotonicity");
  // For merge/group, fill bin IDs
  if (action === "merge_bins" || action === "group_categories") {
    const binInput = screen.getByPlaceholderText("e.g. b1, b2");
    await user.type(binInput, "b1, b2");
  }
}

describe("ManualBinningEditDialog", () => {
  afterEach(() => server.resetHandlers());

  it("renders the dialog with variable name", () => {
    renderDialog();
    expect(screen.getByText(/Edit — income/)).toBeTruthy();
  });

  it("requires reason code and reason text for Preview", async () => {
    const user = userEvent.setup();
    renderDialog();
    const previewBtn = screen.getByText("Preview");
    expect(previewBtn).toBeDisabled();

    await fillReason(user);
    expect(previewBtn).not.toBeDisabled();
  });

  it("requires at least two source bin IDs for merge_bins", async () => {
    const user = userEvent.setup();
    renderDialog();
    // Fill reason WITHOUT bin IDs
    const textarea = screen.getByPlaceholderText("Describe why this edit is needed…");
    await user.type(textarea, "Test.");
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[selects.length - 1], "monotonicity");
    // Only one bin ID — should be rejected
    const binInput = screen.getByPlaceholderText("e.g. b1, b2");
    await user.type(binInput, "b1");

    await user.click(screen.getByText("Preview"));
    expect(screen.getByText(/requires at least two source bin IDs/)).toBeTruthy();
  });

  it("Save is disabled before a successful preview", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(/\/plans\/.*\/steps\/.*\/manual-binning\/preview/, () => {
        return HttpResponse.json({ valid: true, diagnostics: { override_count: 1, warnings: [] }, refined_bins_by_variable: { income: { bins: [{ label: "merged" }] } } });
      }),
    );
    renderDialog();
    const saveBtn = screen.getByText("Save");
    expect(saveBtn).toBeDisabled();

    await fillReason(user);
    expect(saveBtn).toBeDisabled();

    await user.click(screen.getByText("Preview"));
    await waitFor(() => expect(saveBtn).not.toBeDisabled());
  });

  it("Save stays disabled when preview is invalid", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(/\/plans\/.*\/steps\/.*\/manual-binning\/preview/, () =>
        HttpResponse.json({ valid: false, diagnostics: { override_count: 1, warnings: ["Invalid merge"] }, refined_bins_by_variable: {} }),
      ),
    );
    renderDialog();
    await fillReason(user);

    await user.click(screen.getByText("Preview"));
    await waitFor(() => expect(screen.getByText(/Preview invalid/)).toBeTruthy());
    expect(screen.getByText("Save")).toBeDisabled();
  });

  it("preview sends current overrides plus proposed override", async () => {
    const user = userEvent.setup();
    let sentBody: Record<string, unknown> | undefined;
    server.use(
      http.post(/\/plans\/.*\/steps\/.*\/manual-binning\/preview/, async ({ request }) => {
        sentBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({ valid: true, diagnostics: { override_count: 1, warnings: [] }, refined_bins_by_variable: { income: { bins: [] } } });
      }),
    );
    renderDialog();
    await fillReason(user);

    await user.click(screen.getByText("Preview"));
    await waitFor(() => expect(sentBody).toBeTruthy());
    expect((sentBody!.overrides as unknown[]).length).toBe(2);
    expect((sentBody!.overrides as Record<string, unknown>[])[1].variable).toBe("income");
  });

  it("revert requires reason code and text", async () => {
    const user = userEvent.setup();
    renderDialog();
    const revertBtn = screen.getByText("Revert to automated");
    expect(revertBtn).toBeDisabled();

    await fillReason(user);
    expect(revertBtn).not.toBeDisabled();
  });

  it("revert sends reason_code and review_reason to server", async () => {
    const user = userEvent.setup();
    let sentBody: Record<string, unknown> | undefined;
    server.use(
      http.post(/\/plans\/.*\/steps\/.*\/manual-binning\/review/, async ({ request }) => {
        sentBody = await request.json() as Record<string, unknown>;
        return HttpResponse.json({ plan_id: PLAN_ID, new_plan_version_id: "pv2", reviewed: false, accept_automated: false });
      }),
    );
    renderDialog();
    await fillReason(user);

    await user.click(screen.getByText("Revert to automated"));
    await waitFor(() => expect(sentBody).toBeTruthy());
    expect(sentBody!.reason_code).toBe("monotonicity");
    expect(sentBody!.review_reason).toBe("Test merge.");
    expect(Array.isArray(sentBody!.overrides)).toBe(true);
  });
});
