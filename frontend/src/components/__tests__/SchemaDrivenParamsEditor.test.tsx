import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api } from "../../api/client";
import { SchemaDrivenParamsEditor } from "../params/SchemaDrivenParamsEditor";

vi.mock("../../api/client", () => ({
  api: {
    getNodeTypeSchema: vi.fn(),
    updateStepParams: vi.fn(),
  },
  isApiError: vi.fn(() => false),
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const BASE_PROPS = {
  planId: "p1",
  stepId: "cardre.logistic_regression",
  projectId: "proj1",
  currentParams: {} as Record<string, unknown>,
  basePlanVersionId: "v1",
  nodeType: "cardre.logistic_regression",
  onSaved: () => {},
};

describe("SchemaDrivenParamsEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("selects the method from currentParams.method when valid", async () => {
    (api.getNodeTypeSchema as ReturnType<typeof vi.fn>).mockResolvedValue({
      node_type: "cardre.logistic_regression",
      version: "1",
      title: "Logistic Regression",
      methods: [
        { id: "logistic", label: "Logistic", status: "available", params: [] },
        { id: "ridge", label: "Ridge", status: "available", params: [] },
      ],
      params_schema: {},
      defaults: {},
      description: "",
    });

    renderWithClient(
      <SchemaDrivenParamsEditor {...BASE_PROPS} currentParams={{ method: "ridge" }} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Ridge")).toBeTruthy();
    });
  });

  it("falls back to the first available method when currentParams.method is unset", async () => {
    (api.getNodeTypeSchema as ReturnType<typeof vi.fn>).mockResolvedValue({
      node_type: "cardre.logistic_regression",
      version: "1",
      title: "Logistic Regression",
      methods: [
        { id: "logistic", label: "Logistic", status: "available", params: [] },
        { id: "ridge", label: "Ridge", status: "available", params: [] },
      ],
      params_schema: {},
      defaults: {},
      description: "",
    });

    renderWithClient(<SchemaDrivenParamsEditor {...BASE_PROPS} currentParams={{}} />);

    await waitFor(() => {
      expect(screen.getByText("Logistic")).toBeTruthy();
    });
  });

  it("shows loading state while schema is being fetched", () => {
    (api.getNodeTypeSchema as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));

    renderWithClient(<SchemaDrivenParamsEditor {...BASE_PROPS} currentParams={{}} />);

    expect(screen.getByText("Loading schema...")).toBeTruthy();
  });

  it("falls back to RawJsonParamsFallback when schema has no methods", async () => {
    (api.getNodeTypeSchema as ReturnType<typeof vi.fn>).mockResolvedValue({
      node_type: "cardre.logistic_regression",
      version: "1",
      title: "Logistic Regression",
      methods: [],
      params_schema: {},
      defaults: {},
      description: "",
    });

    renderWithClient(<SchemaDrivenParamsEditor {...BASE_PROPS} currentParams={{}} />);

    await waitFor(() => {
      expect(screen.getByText("Parameters")).toBeTruthy();
    });
  });

  it("renders a disabled banner and hides Save when schema.available is false", async () => {
    (api.getNodeTypeSchema as ReturnType<typeof vi.fn>).mockResolvedValue({
      node_type: "cardre.gradient_boosting_classifier",
      version: "1",
      title: "Gradient Boosting",
      methods: [{ id: "gbdt", label: "GBDT", status: "available", params: [] }],
      params_schema: {},
      defaults: {},
      description: "",
      available: false,
      disabled_reason: "Not available in launch mode.",
    });

    renderWithClient(<SchemaDrivenParamsEditor {...BASE_PROPS} nodeType="cardre.gradient_boosting_classifier" />);

    await waitFor(() => {
      expect(screen.getByText(/not available in launch mode/i)).toBeTruthy();
    });
    expect(screen.queryByRole("button", { name: /save params/i })).toBeNull();
    expect(api.updateStepParams).not.toHaveBeenCalled();
  });
});
