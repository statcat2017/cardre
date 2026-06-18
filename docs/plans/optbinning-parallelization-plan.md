# OptBinning Integration — Parallel Development Plan

## Dependency graph

```
Phase 1 (skeleton)
  │
  ├─→ Phase 2 (fit numerical) ──────────────────────────────┐
  │     │                                                     │
  │     ├─→ Phase 3 (categorical/special)                    │
  │     │                                                     │
  │     ├─→ Phase 4 (frozen spec / apply) ────┐              │
  │     │                                       │              │
  │     ├─→ Phase 5 (manual review) ────┐      │              │
  │     │                                 │      │              │
  │     ├─→ Phase 6 (warnings/stability) │      │              │
  │     │     needs: Phase 2 + Phase 4   │      │              │
  │     │                                 │      │              │
  │     └─→ Phase 7 (audit export) ──────┤──────┤              │
│           needs: Phase 2 + Phase 5     │      │              │
│                                         ↓      ↓              │
│                                     Integration testing ─────┘
```

**Critical path**: Phase 1 → Phase 2 → Phase 4 → Phase 6 → integration  
**Length**: 5 phases on critical path  
**Total phases**: 7 (2 off critical path: Phase 3 and Phase 5 can execute in parallel with Phase 4 once Phase 2 is done)

---

## Six parallel work streams

### Stream A — Backend engine (critical path)

| Step | Duration | Depends on | Parallel with |
|---|---|---|---|
| A1. Create `cardre/engine/` package, base.py Protocol | 1 unit | — | — |
| A2. `capabilities.py` detection + pyproject.toml optional dep | 1 unit | — | A1, D1 |
| A3. `OptBinningEngine.fit()` numerical only | 2 units | A1 | B1, C1, D2, E1, F1 |
| A4. `AutoBinningFitNode` node type + registry | 1 unit | A3 | B2, D2 |
| A5. Categorical/special/missing params | 1 unit | A3 | A6, C1 |
| A6. FrozenBinningSpec schema + `apply_frozen_bins()` | 2 units | A3 | A5, B2, D4 |
| A7. Stability checker (`stability.py`) | 1 unit | A6 | C2 |

**Stream A total**: 9 units (5 sequential on critical path)

### Stream B — API layer

| Step | Duration | Depends on | Parallel with |
|---|---|---|---|
| B1. `GET /api/binning/engines` + Pydantic models | 1 unit | A1 | A3, D1 |
| B2. `POST /api/runs/{run_id}/nodes/auto-binning-fit` | 1 unit | A4 + B1 | A6, D2 |
| B3. `GET .../variables/{var}/bin-table` | 0.5 unit | A4 + B1 | A6 |
| B4. `POST .../nodes/binning-review` + `POST .../nodes/binning-apply` | 1 unit | Phase 5 + Phase 4 | C2, D5 |

**Stream B total**: 3.5 units (all off critical path except B2 waits for A4)

### Stream C — Frontend

| Step | Duration | Depends on | Parallel with |
|---|---|---|---|
| C1. `ParamsEditor` progressive disclosure (basic/advanced tabs) | 1 unit | — | A3, B1 |
| C2. `AutoBinningNode.tsx` creation form | 1 unit | B2 | A5, B4 |
| C3. Variable list sidebar (`VariableListSidebar.tsx`) | 1 unit | B3 | A6 |
| C4. `BinningReviewScreen.tsx` with charts/bin-table/actions | 1.5 units | Phase 5 + B4 | D3 |
| C5. `ArtifactBrowser.tsx` WOE preview extension | 0.5 unit | Phase 4 | D4 |

**Stream C total**: 5 units (all off critical path, can mostly run alongside backend)

### Stream D — Manual review extensions (independent)

| Step | Duration | Depends on | Parallel with |
|---|---|---|---|
| D1. Implement `isolate_missing` override action | 0.5 unit | — | A1, B1 |
| D2. Implement `isolate_special_value` override action | 0.5 unit | — | D1, A3 |
| D3. Implement `reject_variable` override action | 0.5 unit | — | D2, A4 |
| D4. Override history logging (immutable events) | 1 unit | D1, D2, D3 | A6, C4 |
| D5. ManulaBinningService extension for new actions | 0.5 unit | D4 | B4, C4 |
| D6. Test: manual overrides on optbinning bins | 0.5 unit | A4 + D4 | A7 |

**Stream D total**: 3.5 units (fully independent of Stream A after Phase 1. All override actions work against the existing `SCHEMA_BIN_DEFINITION` format. New actions can be developed and tested with `FineClassingNode` output before optbinning exists.)

### Stream E — Warnings module (independent)

| Step | Duration | Depends on | Parallel with |
|---|---|---|---|
| E1. `warnings.py` pure check functions | 1 unit | — | A3, C1 |
| E2. Integrate warnings into `AutoBinningFitNode` | 0.5 unit | A4 + E1 | A5 |
| E3. Warning display in review screen | 0.5 unit | E2 + C4 | D5 |

**Stream E total**: 2 units (warnings are pure functions operating on bin dicts; can be developed and unit-tested before any optbinning integration)

### Stream F — Testing

| Step | Duration | Depends on | Parallel with |
|---|---|---|---|
| F1. Fixture Parquet/JSON files (small binary, categorical, special-codes, missing) | 1 unit | — | A1, D1 |
| F2. Unit tests: parameter mapping, numerical fit, manifest | 1.5 units | A4 | B2, C1 |
| F3. Unit tests: categorical, special codes, missing | 1 unit | A5 | A6, C2 |
| F4. Equivalence test: optbinning transform vs Cardre apply | 1 unit | A6 | C3, D4 |
| F5. Integration test: full pathway | 1 unit | A7, D6, E2 | C5 |
| F6. Golden tests (expected artefacts) | 1 unit | A6 | D5 |

**Stream F total**: 6.5 units (most can start as soon as their target phase is implemented)

---

## Optimized schedule (by time unit)

```
Unit  │ Stream A              │ Stream B        │ Stream C           │ Stream D          │ Stream E          │ Stream F
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  1   │ A1. engine/ package   │                 │                    │ D1. isolate_miss  │                   │ F1. fixtures
      │ A2. capabilities      │                 │                    │                   │                   │
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  2   │ A3. fit numerical     │ B1. engines ep  │ C1. params editor  │ D2. isolate_spec  │ E1. warnings.py   │
      │                       │                 │                    │ D3. reject_var    │                   │
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  3   │ A3. fit numerical     │ B1. models      │ C1. params editor  │ D4. override hist │ E1. warnings.py   │
      │   (cont.)             │                 │                    │                   │                   │
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  4   │ A4. AutoBinningNode   │ B2. fit ep      │                    │ D4. override hist │                   │ F2. unit: num fit
      │                       │ B3. bin-table   │                    │                   │                   │
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  5   │ A5. categorical       │                 │ C2. binning form   │ D5. service ext   │ E2. warn integrate │ F2. unit (cont.)
      │ A6. frozen spec       │                 │                    │                   │                   │
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  6   │ A6. frozen spec       │ B4. review+app  │ C3. var sidebar    │ D6. test overrid  │                   │ F3. unit: cat
      │                       │                 │                    │                   │                   │ F4. equiv test
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  7   │ A7. stability         │                 │ C4. review screen  │                   │ E3. warn in UI    │ F4. equiv (cont.)
      │                       │                 │                    │                   │                   │ F6. golden tests
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  8   │                       │                 │ C4. review (cont.) │                   │                   │ F5. integration
      │                       │                 │ C5. WOE preview    │                   │                   │
──────┼───────────────────────┼─────────────────┼────────────────────┼───────────────────┼───────────────────┼──────────────────
  9   │ Phase 7 audit export  │                 │                    │                   │                   │
```

**Total**: 9 time units on critical path  
**Without parallelization**: 23 time units (sequential sum of all phases)

---

## Parallelization gains

| Metric | Sequential | Parallel | Saving |
|---|---|---|---|
| Critical path length | 23 | 9 | 61% |
| Max concurrent streams | 1 | 6 | — |
| Independent work at unit 1 | 0% | 33% (3 of 6 streams active) | — |
| Independent work at unit 3 | 0% | 100% (all 6 streams active) | — |
| Stream D fully independent after Phase 1 | — | Yes | Manual review decoupled |
| Stream E fully independent until integration | — | Yes | Warnings decoupled |
| Stream F fixtures independent of everything | — | Yes | Tests can start day 1 |

---

## Key parallelization enablers

### 1. Override actions are schema-compatible, not engine-specific

`isolate_missing`, `isolate_special_value`, and `reject_variable` operate on the bin definition dict format (`SCHEMA_BIN_DEFINITION`). They work identically whether the bins came from `FineClassingNode` (Polars qcut) or `AutoBinningFitNode` (optbinning). This means **Stream D can start on day 1** — implement and test the new override actions against existing `FineClassingNode` output. Integration with optbinning is a single test (`D6`) added at the end.

### 2. Warnings are pure functions

`check_pure_bins()`, `check_sparse_bins()`, `check_monotonic_woe()` take `list[dict]` (bin dicts) and return `list[BinningWarning]`. They have zero runtime dependencies beyond Python stdlib. **Stream E can start on day 2** — design and unit-test all warning checks with hand-crafted bin dicts. Integration into `AutoBinningFitNode` is a single function call (`E2`).

### 3. Fixtures are usable by all streams

The four test fixture files (small binary, categorical, special-codes, missing) serve as shared ground truth for:
- `F2` parameter mapping tests
- `F3` categorical/special tests
- `F4` equivalence tests
- `F5` integration tests
- `F6` golden tests

**Stream F starts on day 1** creating fixtures; all other test steps reference them.

### 4. Frontend components are generic

`ParamsEditor` progressive disclosure is a generic component (not optbinning-specific). `VariableListSidebar` is a generic list with status badges. These can be developed against mock API responses before any backend exists. **Stream C can start on day 2**.

### 5. API shapes stabilize at Phase 1

Once `BinningEngine` Protocol and `BinningFitResult` dataclass are defined, the API request/response shapes are locked. Stream B can implement endpoints against stubs. Stream C can build UI against mock responses.

---

## Assignment model (3 developers)

```
Dev 1 (Backend lead):  Stream A full path
                        Hand-off: Phase 4 frozen spec to Dev 3 for Stream F testing

Dev 2 (Full-stack):     Stream B (API) → Stream C (Frontend)
                        Hand-off: API endpoints to Dev 3 for integration tests

Dev 3 (QA + infra):     Stream D (manual review) → Stream E (warnings) → Stream F (testing)
                        Starts fixtures day 1, tests every stream as it delivers
```

### Developer schedule

```
Unit │ Dev 1 (backend)              │ Dev 2 (API+UI)              │ Dev 3 (QA+review)
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  1  │ A1. engine/ package          │ Review A1 design            │ F1. fixtures
     │ A2. capabilities             │                             │ D1. isolate_missing
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  2  │ A3. OptBinningEngine.fit()   │ B1. GET /engines + models   │ D2. isolate_special
     │                              │                             │ D3. reject_variable
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  3  │ A3. (cont.)                  │ B1. (cont.)                 │ D4. override history
     │                              │ C1. ParamsEditor            │ E1. warnings.py
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  4  │ A4. AutoBinningFitNode       │ B2. POST fit endpoint       │ D4. (cont.)
     │                              │ B3. GET bin-table           │ F2. unit: numerical fit
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  5  │ A5. categorical/special      │ C2. AutoBinningNode.tsx     │ D5. service extension
     │ A6. frozen spec design       │                             │ E2. warn integration
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  6  │ A6. apply_frozen_bins()      │ B4. review + apply eps      │ F3. unit: categorical
     │                              │ C3. VariableListSidebar     │ F4. equivalence test
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  7  │ A7. stability.py             │ C4. BinningReviewScreen     │ D6. test: manual override
     │                              │                             │ F4. (cont.)
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  8  │ Phase 7 audit export         │ C4. (cont.)                 │ F6. golden tests
     │                              │ C5. WOE artifact preview    │ F5. integration test
─────┼──────────────────────────────┼─────────────────────────────┼──────────────────────
  9  │ Phase 7 (cont.)              │ Polish + types refresh      │ F5. (cont.)
```

No two developers block on the same file at the same time. The only shared files are:
- `cardre/registry.py` (Dev 1 adds node; Dev 3 reads for test setup)
- `sidecar/routes/node_types.py` (Dev 2 adds schema; Dev 1 adds stub earlier)
- `sidecar/models.py` (Dev 1 defines core; Dev 2 extends with API models)

These are non-conflicting additions.

---

## Risk: single developer

If only one developer, follow this order to maximize velocity:

1. **Day 1-2**: A1 + A2 + F1 + D1/D2/D3 (engine skeleton + fixtures + manual review stubs)
2. **Day 3-5**: A3 + D4 + E1 + B1 (core engine + override history + warnings + capabilities API)
3. **Day 6-8**: A4 + A5 + F2 + B2/B3 (AutoBinningNode + categorical + unit tests + fit API)
4. **Day 9-11**: A6 + F3/F4 + B4 (frozen spec + apply + equivalence tests + apply API)
5. **Day 12-14**: C1/C2/C3/C4 (frontend — build when API is stable)
6. **Day 15-17**: A7 + E2/E3 + F5/F6 (stability + warning integration + golden + integration tests)
7. **Day 18-19**: Phase 7 (audit export)
8. **Day 20**: Polish, types refresh, final integration pass

**Total**: ~20 days single-developer. Parallelization with 3 devs compresses to ~9 days.

---

## Shared artifacts that unlock parallelism

| Artifact | Created in | Unlocks |
|---|---|---|
| `BinningFitRequest` / `BinningFitResult` dataclasses | A1 (Phase 1) | Stream B (API), Stream F (tests) |
| `VariableBinningResult` + `BinningBin` dataclasses | A1 (Phase 1) | Stream D (manual review), Stream E (warnings) |
| Test fixtures (4 Parquet files) | F1 (day 1) | All test streams |
| `SCHEMA_BIN_DEFINITION` (already exists in `evidence.py`) | Pre-existing | Stream D operates against this directly |
| `NodeType` ABC (already exists in `audit.py`) | Pre-existing | Stream A builds on this; no new abstraction needed |
| API Pydantic models | B1 (unit 2) | Stream C (frontend) starts building UI |

The key insight: **Phase 1 delivers the data contracts**. Once `BinningFitRequest`, `BinningFitResult`, `VariableBinningResult`, and `BinningBin` are defined, every other stream can proceed independently against those contracts. The actual optbinning implementation comes later in Phase 2 but the contract is enough.

---

## Where sequential execution is unavoidable

| Dependency | Why it must be sequential |
|---|---|
| A3 (engine.fit) after A1 (base.py) | Interface must exist before implementation |
| A4 (AutoBinningNode) after A3 (engine) | Node wraps engine; needs engine to be testable |
| A6 (apply) after A3 (engine) | Apply logic needs to match engine output shape |
| B2 (fit endpoint) after A4 (node) | Endpoint wraps node execution |
| C2 (UI form) after B2 (API) | UI needs API contract to build form |
| F2 (unit tests) after A4 (node) | Tests exercise the node |
| F4 (equivalence) after A6 (apply) | Equivalence compares engine.transform vs Cardre.apply |
| F5 (integration) after A7, D6, E2 | End-to-end needs all components |

**Irreducible critical path**: A1 → A3 → A4 → B2 → C2 (5 steps; cannot be parallelized further)
