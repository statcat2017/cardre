# Phase 7 — Frontend test infrastructure + journey acceptance tests

You are implementing **Phase 7** of the Guided Workflow Sprint
(`docs/plans/guided-workflow-sprint.md`). Phases 2, 3, 4, and 6 are merged.
This phase is **not** a hard prerequisite for any other, but its CI job
should land before the sprint's DoD sign-off.

This phase is bigger than the original "PR 7" implied. The repo's
`frontend/package.json` has **no test dependencies**. CI runs only
`npx tsc --noEmit`. Land the infra first, then the journey scenarios.

Read first:
- `frontend/package.json`
- `.github/workflows/ci.yml` (specifically
  `typecheck-frontend`)
- `frontend/src/api/client.ts` (need API injection design)
- `frontend/src/App.tsx` (entry point; how `QueryClientProvider` is set up)

## Goal

1. Land a Vitest + @testing-library/react + **msw** stack and a CI job
   that fails the build on regressions.
2. Implement six journey acceptance tests at the *product* level
   (`Phase 2`, `Phase 3`, `Phase 6` paths). User-visible state only — not
   implementation details.
3. Make the API client mockable so `JourneyHeader`/`PathwayView`/
   `StepInspector` can be tested without hitting a real backend.

## Dependencies

Add to `frontend/package.json` (devDependencies):

- `vitest`
- `@vitest/ui` (optional but useful)
- `@testing-library/react`
- `@testing-library/jest-dom`
- `@testing-library/user-event`
- `jsdom`
- `msw`

Add scripts:

```json
"test": "vitest run",
"test:watch": "vitest",
"test:ui": "vitest --ui"
```

Add a `vitest.config.ts` at `frontend/`:

```ts
/// <types:vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
```

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

## API Mocking Design

`client.ts` constructs `fetch` URLs against `getBaseUrl()`. To make this
mockable in tests without monkeypatching imports:

- `getBaseUrl()` already reads `window.__API_URL__`. Tests can set
  `window.__API_URL__ = ""` (relative routes) and **msw** intercepts the
  relative fetch. This is the lowest-friction design and does not require
  refactoring `client.ts`.

`frontend/src/test/server.ts`:

```ts
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const server = setupServer(
  // default handlers — per-test files override with server.use(...)
  http.get("/plans/:planId/workflow-guidance", () => HttpResponse.json({
    phase: "build",
    next_action: { kind: "configure_step", label: "Configure target", description: "...", run_scope: null, step_id: "target-definition", action_target: null },
    blockers: [],
    step_guidance: {},
    report_readiness: null,
    branch_id: "br_baseline",
    run_id: null,
  })),
  // ... etc for every endpoint the journey tests touch
);

export { server };
```

Per-test files override via:

```ts
import { server } from "../test/server";
import { http, HttpResponse } from "msw";

server.use(
  http.get("/plans/:planId/workflow-guidance", () => HttpResponse.json({
    phase: "setup",
    next_action: { kind: "import_dataset", ... },
    ...
  })),
);
```

## Journey Acceptance Tests

`frontend/src/components/__tests__/journey.test.tsx` — covers the six
scenarios from the sprint DoD:

1. **Project with no dataset** → phase is `setup`; TopBar's CTA label is
   "Import dataset"; clicking switches central pane to dataset section.
   State assertion: `ProjectView`'s `activeSection === "dataset"` after
   click. Mock `useWorkflowGuidance` response with `phase: "setup"` and
   `next_action.kind: "import_dataset"`. Mock `api.getProjectPlans` to
   return a minimal plan; mock `api.getProject` to return a minimal
   project; mock `api.listBranches` to return one baseline branch so
   Phase 0's BranchSelector settled.

2. **Imported dataset** with `step_guidance["target-definition"].readiness
   == "needs_config"` → CTA is "Configure target"; clicking selects the
   step. Assertion: `selectedStepId === "target-definition"` after click;
   `StepInspector` renders the manual-binning *absence* (i.e. params
   editor path is the configure tab if Phase 4 landed, or the collapsible
   params editor if Phase 4 didn't merge yet).

3. **After run with stale step** → JourneyHeader shows a stale/blocker
   pill. Mock `useRunProgress`'s completed-run invalidation flow by
   pre-seeding React Query cache: `[["plan", planId]]` with a step whose
   `is_stale === true`. Phase 3's PathwayView renders the
   `canonicalizeStepId`-derived `readiness: "stale"` and the card shows
   the plain-English copy "Stale — upstream has changed". Assert by text
   query.

4. **Manual binning ready** → guidance says
   `step_guidance["manual-binning"].readiness == "ready"`; PathwayCard
   shows "Ready to edit N selected variables" (Phase 5a) and StepInspector
   shows the "Edit Bins" button. Assert the button is enabled; click
   opens `ManualBinningEditor` (Phase 5a or legacy block — both paths
   covered by `setEditingStepId`).
   - If Phase 5a has not merged, this test asserts against the **legacy**
     manual-binning readiness block. The test file must use feature-aware
     selectors (e.g. button with text "Edit Bins") so it survives 5a.

5. **Report readiness blocked** with at least one blocker carrying
   `step_id` → ExportPanel renders the blocker with a "Go to step" button;
   clicking switches to pathway and selects the step. This scenario also
   asserts JourneyHeader badge shows "Report blocked (N)".
   - Mock `useReportReadiness` (Phase 6's shared hook) to return
     `{ ready: false, blockers: [{code, step_id, message}], warnings: [] }`.

6. **Report ready** → JourneyHeader (TopBar ribbon) shows phase `ready`;
   CTA reads "Open exports"; clicking switches to exports section. Report
   readiness shows "Ready" in the ExportPanel.

## Other Required Tests (Smoke)

Add small smoke files so test infra has a baseline:

- `frontend/src/test/getBaseUrl.test.ts` — `window.__API_URL__` override
  works; default fall-back holds.
- `frontend/src/config/__tests__/stepDisplayMetadata.test.ts` —
  `canonicalizeStepId("manual-binning__br_xxx") === "manual-binning"` and
  pure function.

## CI Job

In `.github/workflows/ci.yml`, add `test-frontend` after
`typecheck-frontend`:

```yaml
  test-frontend:
    runs-on: ubuntu-latest
    needs: [typecheck-frontend]
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npm test
```

Update `package-lock.json` via `npm install` (not via the lockfile manually
unless necessary).

Pre-commit checks on local dev:

```bash
cd frontend && npm test && npx tsc --noEmit
```

## Files

| File                                              | Action | Content                                                                                          |
|---------------------------------------------------|--------|--------------------------------------------------------------------------------------------------|
| `frontend/package.json`                           | Edit   | Add dev deps + test scripts.                                                                     |
| `frontend/package-lock.json`                      | Regen  | `npm install`.                                                                                   |
| `frontend/vitest.config.ts`                       | Create | Vitest + jsdom + plugin-react.                                                                   |
| `frontend/src/test/setup.ts`                      | Create | Imports jest-dom matchers; starts/stops msw server.                                              |
| `frontend/src/test/server.ts`                     | Create | Default msw handlers for endpoints used by tests.                                                |
| `frontend/src/test/fixtures.ts`                   | Create | Reusable typed fixtures (project, plan, branch, run steps, guidance). Keep small.               |
| `frontend/src/components/__tests__/journey.test.tsx` | Create | Six journey scenarios.                                                                            |
| `frontend/src/config/__tests__/stepDisplayMetadata.test.ts` | Create | canonicalization tests.                                                              |
| `frontend/src/test/getBaseUrl.test.ts`            | Create | window URL override.                                                                              |
| `.github/workflows/ci.yml`                        | Edit   | Add `test-frontend` job.                                                                          |
| `README.md`                                       | Edit   | Add `npm test` line to "Frontend" section.                                                       |

## Sequence

1. Add dep entries to `package.json` (`vitest`, etc.).
2. `npm install` to regenerate `package-lock.json`.
3. Create `vitest.config.ts`, `src/test/setup.ts`, `src/test/server.ts`,
   `src/test/fixtures.ts`.
4. Run `npm test` — should pass with zero tests; infra wired.
5. Add the smoke tests. Run.
6. Add the six journey tests one by one. Each fails-passes-iterate.
7. Add CI job. Push to a branch and confirm CI runs `test-frontend`.
8. Update README.md with test command.

## Acceptance Criteria

- `cd frontend && npm test` runs all six journey scenarios + smoke tests
  and exits 0.
- Consecutive `vitest run` invocations are idempotent (no global state
  leaks between tests).
- CI `test-frontend` job runs and is required on PRs into `main`.
- msw server is the only way tests reach the API — no accidental network
  calls. `onUnhandledRequest: "error"` catches drift if a new endpoint is
  hit without a handler.
- Each of the six scenarios from the sprint DoD passes. Tests assert
  **user-visible** state (button labels, the section the UI switched to, the
  presence of plain-English copy) — never implementation details like
  internal state keys.

## Non-Goals

- E2E tests in Playwright/Tauri (out of scope for this sprint — keep
  component tests at the product-journey level).
- Visual regression / snapshot tests.
- Coverage thresholds (the DoD says CI catches journey breaks; do not gate
  on coverage percentage).
- Snapshotting the entire DOM — text-based assertions only.

## Drop-Dead Notes

- msw's `onUnhandledRequest: "error"` means any new handler missed by a
  test will fail loudly. When implementing, prefer fewer well-named
  handlers in `server.ts` that tests override, over giant per-test handlers.
- Avoid snapshot tests. They rot fast and obscure user intent. Use
  `getByRole`, `getByText`, `findByText` queries.
- The journey tests must not depend on real timing. Use `userEvent.setup()`
  with `advanceTimers` if needed, but React Query's `staleTime: 2000` is
  not relevant in tests because msw responds synchronously. If
  `useRunProgress`'s `setInterval` poll interferes, mock the hook at the
  test boundary.
- If a phase merge ordering means Phase 4 or Phase 5a is missing when
  Phase 7 lands, the journey tests must assert against the **low-level
  user-visible behaviour** (e.g., button text "Edit Bins") which both the
  legacy and Phase-4/5a implementations surface. Do not pin to internal
  component names (e.g., "Next action tab label").
- If `vitest`'s `React` plugin and `vite-react` conflict with `vite build`,
  add a `vitest.config.ts` separate from `vite.config.ts` — they may
  diverge. Do not modify `vite.config.ts`.