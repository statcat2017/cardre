# PRD: Cardre v2 Big-Bang Refactor

## Problem Statement

Cardre is intended to be an auditable, local-first credit scorecard builder, but the current v1 architecture still carries several structural habits that make auditability harder than it needs to be. Evidence is partly reconstructed from run-step JSON, plan graph relationships still live in JSON arrays, governance routes are conditionally mounted, run coordination is clearer than it used to be but still named and packaged like a generic service, manual binning is not treated as a first-class governed review workflow, and the API is not uniformly project-scoped.

Cardre has not launched and there are no existing user projects. That means there is no backwards-compatibility requirement for existing `.cardre` directories or external consumers. The team can use a clean v2 branch to reshape the product around the domain concepts that matter: Project, PlanVersion, Step, Run, and Evidence.

From the user's perspective, the problem is that Cardre v1 can build scorecard components, but the product is not yet organised around the questions regulated scorecard users need answered: exactly what happened, why this evidence was used, whether it was reused, whether it is stale, which plan version caused it, and whether the UI/API/store all agree.

## Solution

Build Cardre v2 as a big-bang refactor on a long-lived `v2` branch, then merge to `main` only when the full v2 acceptance path is green. v2 will preserve the broad stack: Python engine, FastAPI local API, React/Tauri desktop shell, SQLite metadata, and filesystem artifacts. It will not preserve v1 schema compatibility or v1 module boundaries.

The primary acceptance seam is the project-scoped local API. The highest-level acceptance path is: create a project, create a plan, run the launch scorecard pathway, persist evidence edge and artifact rows, explain staleness, complete a manual-binning review, generate reports, and export an audit bundle. Lower seams such as domain, store, and execution tests are phase-local scaffolding used before the full API exists.

The refactor will introduce a clean domain kernel, a relational store with no queryable JSON relationship arrays, a two-level evidence model, a manual-binning review workflow, recoverable run coordination, generated frontend types, and governance routes that are always mounted but capability-gated.

## User Stories

1. As a scorecard analyst, I want to create a local Cardre project, so that all scorecard metadata and artifacts stay on my machine.
2. As a scorecard analyst, I want every project to have a clear schema family and schema version, so that I am never silently opening an incompatible project directory.
3. As a scorecard analyst, I want to create a plan as a versioned document of intent, so that I can separate what I intended to build from what actually ran.
4. As a scorecard analyst, I want plan versions to distinguish draft and committed states, so that I can edit a working draft without creating a permanent version for every small change.
5. As a scorecard analyst, I want committed plan versions to be immutable, so that historical runs remain tied to a stable build intent.
6. As a scorecard analyst, I want each step to represent one typed node invocation in a plan, so that the build pathway is explicit and auditable.
7. As a scorecard analyst, I want plan step parent-child relationships to be queryable rows, so that the plan graph can be inspected without parsing JSON arrays.
8. As a scorecard analyst, I want to import a dataset as an immutable artifact, so that downstream steps can cite exactly which data was used.
9. As a scorecard analyst, I want artifacts to have physical and logical hashes, so that bit-level integrity and reproducibility can be checked separately.
10. As a scorecard analyst, I want train, test, and out-of-time artifacts to be role-tagged, so that fitting and validation streams cannot be confused.
11. As a scorecard analyst, I want fitting nodes to consume only train evidence, so that validation leakage is prevented by the executor.
12. As a scorecard analyst, I want validation nodes to apply fitted definitions to test and out-of-time data, so that holdout performance is measured correctly.
13. As a scorecard analyst, I want every run to have a strict lifecycle, so that created, queued, running, succeeded, failed, cancelled, and interrupted states are unambiguous.
14. As a scorecard analyst, I want run request fields to be persisted at run creation, so that async runs can be recovered and executed from the database using only the run identifier.
15. As a scorecard analyst, I want sync and async runs to produce equivalent summaries and evidence, so that execution mode does not change audit output.
16. As a scorecard analyst, I want every run step to write evidence as it completes, so that partial evidence and diagnostics are not lost if finalisation fails.
17. As a scorecard analyst, I want each parent evidence relationship to be recorded as an evidence edge, so that I can see which upstream step supplied evidence to a consuming step.
18. As a scorecard analyst, I want each artifact consumed through an evidence edge to be recorded separately, so that train, test, and out-of-time artifacts remain inspectable.
19. As a scorecard analyst, I want evidence reuse to be explicit, so that I can tell when a run reused prior evidence instead of recomputing a step.
20. As a scorecard analyst, I want stale evidence explanations to be computed from plan version, params hash, graph edges, evidence, and logical hashes, so that stale state is never a mutable flag that drifts from reality.
21. As a scorecard analyst, I want historical evidence rows never to be rewritten when a new draft exists, so that the audit trail remains truthful.
22. As a scorecard analyst, I want staleness explanations from the backend, so that the UI does not reconstruct business state locally.
23. As a scorecard analyst, I want manual binning to be a first-class review workflow, so that coarse classing is governed rather than treated as a parameter edit.
24. As a scorecard analyst, I want a manual-binning edit to be one atomic command, so that plan changes, review notes, warnings, and affected steps stay consistent.
25. As a scorecard analyst, I want manual-binning edits to create or update a draft plan version, so that I can iterate before committing the scorecard design.
26. As a scorecard analyst, I want downstream steps after a manual-binning edit to require rerun by construction, so that outdated model results are not presented as current.
27. As a scorecard analyst, I want affected downstream steps to be returned as workflow hints, so that I know what needs attention after a manual-binning review.
28. As a scorecard analyst, I want the authoritative stale answer to come from the staleness service, so that UI hints never become evidence truth.
29. As a scorecard analyst, I want fine classing, WOE/IV, variable selection, manual binning, WOE transform, logistic regression, score scaling, validation metrics, cutoff analysis, reporting, and export to form the launch pathway, so that Cardre can produce a complete scorecard build.
30. As a scorecard analyst, I want WOE/IV evaluation and WOE transform to remain distinct, so that variable ranking and data transformation are not conflated.
31. As a scorecard analyst, I want the build stream and validate stream to be explicit, so that the scorecard is fitted on train data and validated on holdout data.
32. As a scorecard analyst, I want a report to cite evidence edges and artifacts, so that the report can explain exactly what was used.
33. As a scorecard analyst, I want an audit bundle export, so that I can hand reviewers the evidence trail behind a scorecard.
34. As a scorecard analyst, I want a scorecard JSON export, so that the final model can be consumed by other tooling.
35. As a scorecard analyst, I want Python and SQL scoring code exports, so that the scorecard can be deployed in common execution environments.
36. As a scorecard analyst, I want validation packs, so that model performance and cutoff analysis can be reviewed outside the UI.
37. As a governance reviewer, I want branch, comparison, and champion workflows to use relational evidence, so that challenger governance is queryable and auditable.
38. As a governance reviewer, I want governance routes to be visible in the API but capability-gated, so that OpenAPI, CI, and frontend types do not drift by environment.
39. As a governance reviewer, I want a disabled governance capability to return a structured 403 response, so that the UI can explain why the action is unavailable.
40. As a governance reviewer, I want comparison challengers and snapshot plan-version sources to be rows, so that comparisons are queryable without JSON parsing.
41. As a developer, I want the domain kernel to be importable without store, FastAPI, node registry, or optional modelling dependencies, so that domain objects stay simple and testable.
42. As a developer, I want executable node interfaces to live with node contracts, so that the domain layer does not depend on plugin execution.
43. As a developer, I want execution context and node output types to live in the execution layer, so that execution-specific concerns stay out of the domain kernel.
44. As a developer, I want configuration to stay in a central config module, so that environment parsing does not leak across the codebase.
45. As a developer, I want capability decisions to be derived from central configuration, so that tests can patch configuration without reading environment variables directly.
46. As a developer, I want generated frontend types to be the only frontend API type source, so that schema drift is caught by type checking.
47. As a developer, I want the frontend API client to keep robust error classification, so that sidecar unreachable, timeout, aborted, empty body, malformed JSON, and server-coded failures remain distinguishable.
48. As a developer, I want a central run-watch hook, so that polling and run-state interpretation are not duplicated across UI components.
49. As a developer, I want phase-local CI during the v2 build, so that deleting v1 modules does not force irrelevant v1 tests to pass before their replacements exist.
50. As a developer, I want full preflight only at the final v2-to-main merge gate, so that the branch can be built coherently without pretending it is shippable mid-refactor.
51. As a developer, I want each phase to write a decision log, so that later agent sessions preserve earlier architecture decisions.
52. As a developer, I want v1 tests retained temporarily as a reference source, so that useful characterization cases can be ported without preserving legacy coupling.
53. As a developer, I want stale and lineage behavior tested through the project-scoped API once the full pathway exists, so that acceptance tests cover user-visible behavior rather than implementation details.
54. As a local-first desktop user, I want the Tauri shell and FastAPI sidecar to remain the product shape, so that Cardre stays a local desktop application rather than becoming a hosted service.
55. As a regulated-model user, I want Cardre organised around the evidence trail rather than nodes, so that model outputs are explainable as part of a traceable build pathway.

## Implementation Decisions

- Build v2 on a long-lived `v2` branch and merge to `main` only after the final full preflight gate passes.
- Preserve the broad stack: Python scorecard engine, FastAPI sidecar, React/Tauri desktop shell, SQLite metadata, and filesystem artifacts.
- Do not support v1 project-directory compatibility. v2 creates fresh projects only and hard-errors on incompatible store metadata.
- Keep a hard store safety check with `schema_family`, `schema_version`, and creator version metadata. This is not migration support; it prevents accidental opening of incompatible projects.
- Organise the new architecture around five first-class domain concepts: Project, PlanVersion, Step, Run, and Evidence.
- Keep the domain kernel free of I/O, node-registry, FastAPI, store, and optional modelling dependencies.
- Keep the executable node plugin interface in node contracts, not in the domain layer.
- Keep execution context and node output types in the execution layer, not in the domain layer.
- Keep environment parsing in the central configuration module. Add derived capabilities separately instead of moving configuration into the domain kernel.
- Preserve physical and logical artifact hashes as central audit primitives.
- Use SQLite for metadata only. Tabular data remains in Parquet artifacts; small non-tabular reports, configuration blobs, definitions, and model metadata can remain JSON artifacts.
- Remove all queryable JSON relationship arrays. Plan graph edges, comparison challengers, comparison snapshot sources, lineage, evidence, branch ownership, review status, champion assignment, and diagnostics are relational.
- Replace plan parent-step JSON with explicit plan step edge rows.
- Replace comparison challenger JSON with comparison challenger branch rows.
- Replace comparison snapshot source plan-version JSON with comparison snapshot plan-version rows.
- Split evidence into two relational grains: evidence edges for parent-step relationships and evidence artifacts for artifacts carried through each edge.
- Store evidence reuse, stale status, stale reason, policy, source label, source run, and source run step at the evidence edge level.
- Store artifact identifier and role at the evidence artifact level.
- Keep artifact lineage for artifact outputs and use evidence tables for inputs and resolved evidence.
- Keep run-step execution metadata for diagnostics, code/library versioning, node type, node version, and params hash. Do not use run-step JSON metadata for lineage or staleness.
- Model run steps as execution records without input/output artifact arrays. Use a derived run-step evidence view for input artifacts, output artifacts, and evidence edges.
- Persist run request fields at run creation: run scope, branch, target step, force flag, requester, request identifier, created time, queued time, and started time. Execution by run identifier loads the request fields from the database.
- Rename the run orchestration owner to RunCoordinator. It owns validation, run creation/reuse, short-circuit behavior, dispatch, execution handoff, and recovery.
- Do not recreate the v1 run orchestrator compatibility shim.
- Write evidence edges and evidence artifacts per run step inside the run transaction, not only at run finalisation.
- Keep sync and async execution behavior equivalent. Differences in dispatch substrate must not alter run summary, evidence rows, diagnostics, or manifests.
- Compute staleness from plan version, step params hash, plan graph edges, source run evidence, logical hashes, and manual-binning review state.
- Never rewrite historical evidence rows to mark them stale after a new draft is created.
- Treat manual binning as a governed review object, not as a minor parameter-edit screen.
- Make manual-binning edits one atomic plan mutation command that validates source evidence, creates or updates a draft plan version, updates the manual-binning step, persists review details, and returns affected downstream steps.
- Store affected downstream steps as workflow hints only. The authoritative stale answer comes from the staleness service.
- Introduce a minimal API in the manual-binning phase so the UI spike is end-to-end against a real route, not a mock.
- Expand that minimal API into a full project-scoped API later.
- Keep `/health` global. All product routes are project-scoped.
- Keep plans and plan versions distinct in the API. A plan has versions; a plan version has steps.
- Always mount governance routes. Gate disabled governance behavior through structured 403 responses rather than conditional route registration.
- Use generated OpenAPI frontend types as the single source of frontend API typing. Remove hand-written duplicate frontend API types.
- Preserve the robust frontend API client behavior from v1, including distinct handling of network rejection, request timeout, caller abort, empty bodies, malformed JSON, non-JSON errors, HTML errors, and server error codes.
- Preserve and rename the central run polling hook as a run-watch hook. Components render backend state and should not reconstruct stale/run business state locally.
- Keep launch and deferred node tiers. Do not rename deferred to experimental because deferred means visible-but-not-executable, which is different from unstable-but-executable.
- Add governance or hidden node tiers only when actual nodes need those semantics.
- Keep governance primarily as routes/services/capabilities, not necessarily node tiers.
- Keep v1 tests temporarily in a non-running reference directory for characterization test porting, then delete that directory in the final cleanup phase.
- Use phase-local CI until the v2 branch is complete. Run full preflight only before merging v2 to main.
- Require each implementation phase to produce a short decision log that the next phase reads first.

## Testing Decisions

- The primary acceptance seam is the project-scoped local API. The highest-level test creates a project, creates a plan, runs the launch scorecard pathway, persists evidence edge and artifact rows, explains staleness, performs a manual-binning review, generates reports, and exports an audit bundle.
- Good tests assert external behavior: API responses, persisted evidence rows, staleness explanations, exported artifacts, diagnostics, and user-visible run states. They should not assert private helper call order or internal implementation details.
- Lower seams are allowed only as phase-local scaffolding before the API exists. The aim is to collapse confidence into the API acceptance seam as soon as the API and launch pathway exist.
- Domain tests cover construction and invariants for Project, PlanVersion, Step, Run, Evidence, Artifact, and ManualBinningReview objects.
- Store tests cover fresh schema creation, store metadata safety checks, rejection of v1 project stores, relational plan step edges, evidence edges and artifacts, manual-binning review lifecycle, and transaction rollback.
- Schema tests explicitly prevent regressions to queryable JSON arrays by checking that relationship-like columns are modelled relationally.
- Evidence tests cover the two-level grain: parent-step evidence edge rows and artifact rows attached to each edge.
- Staleness tests cover computed statuses from changed params hashes, missing evidence, changed upstream logical hashes, branch/source evidence resolution, and manual-binning draft changes.
- Manual-binning mutation tests cover the atomic command, rollback on partial failure, creation of a draft plan version, review persistence, affected downstream workflow hints, and non-mutation of historical evidence.
- Manual-binning UI spike tests cover the real minimal API route, not a mocked endpoint.
- Execution tests cover topological ordering, role enforcement, leakage prevention, per-step evidence persistence, failure diagnostics, manifest finalisation, and partial-run evidence survival.
- Run coordination tests cover sync/async equivalence, short-circuit behavior, placeholder cancellation, stale-run recovery, persisted request reconstruction, and terminal state handling.
- API tests cover project-scoped route shapes, distinct plan and plan-version concepts, generated schemas, error envelopes, governance 403 behavior, and health behavior.
- Frontend API-client tests port v1 robustness coverage for sidecar unreachable, timeout, caller abort, empty success body, empty error body, malformed JSON, HTML errors, non-JSON errors, and server-provided error codes.
- Frontend run-watch tests cover run failed, interrupted, stale, stuck, user-cancelled watch, backend-cancelled execution, request timeout, malformed JSON, and sidecar unreachable states.
- Launch pathway tests are the running-code schema acceptance test. They must prove a full import-to-export scorecard run writes evidence edges and evidence artifacts for every step and returns correct staleness explanations.
- Reporting/export tests verify that audit outputs cite evidence, manifests, artifacts, hashes, diagnostics, and scorecard exports consistently.
- Governance tests verify branch, comparison, champion, and deferred-node behavior against relational evidence and capability-gated routes.
- Prior art exists in v1 tests for executor behavior, run lifecycle, run coordination, run worker, staleness, evidence resolver, artifact lineage, API contracts, error envelope, manual binning phases, frontend API robustness, and ProjectView/run progress behavior. These should be ported selectively from the non-running v1 reference test directory.
- Phase-local CI runs only the tests for modules introduced in that phase. Full preflight is required only at the final v2-to-main merge gate.

## Out of Scope

- Opening or migrating existing v1 `.cardre` project directories.
- Backfilling v1 artifact lineage or run-step JSON lineage.
- Maintaining v1 Python import compatibility or re-export shims.
- Keeping v1 route shapes as compatibility aliases.
- Supporting global run or artifact lookup routes outside a project scope.
- Hosted/SaaS deployment. v2 remains local-first desktop software.
- Switching to Electron, a JavaScript modelling engine, or hosted database storage.
- Building advanced ML challenger nodes into the launch pathway.
- Making deferred nodes executable in launch mode.
- Implementing fairness, reject inference, explainability, tuning, XGBoost, LightGBM, CatBoost, or ensemble workflows as launch-scope features.
- Treating governance branch/comparison/champion workflows as part of the launch pathway. They are final-phase functionality.
- Using stale flags written onto historical evidence rows.
- Duplicating frontend API types by maintaining hand-written types alongside generated OpenAPI types.
- Requiring full v1-compatible CI during early v2 phases.

## Further Notes

- The v2 branch should merge to main only at the end, after the final full preflight and PR gate are green.
- Phase 2 may need a second pass after Phase 3 because the initial manual-binning spike uses fixture-inserted evidence before real execution evidence exists. This is expected, not a failure.
- The launch pathway test in the later phase is the real pressure test for the evidence schema. If the schema cannot represent a real full run, revisit the Phase 1 schema rather than patching around it.
- The final local plan is recorded in `docs/plans/v2/cardre-v2-refactor-plan.md` and should be used as the implementation guide alongside this PRD.
- The core product principle is that Cardre v2 is organised around the evidence trail, not around nodes. Nodes are plugins; the architecture is plan mutation, run coordination, evidence resolution, staleness explanation, manual review, and audit export.
