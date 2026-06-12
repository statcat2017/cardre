# Cardre

Cardre is being rebuilt as an open-source, auditable credit scorecard builder.

The core idea is that a scorecard is not just a final model. It is an input
dataset plus a traceable build pathway: profiling, cleaning, binning, WOE/IV,
coarse classing, model fitting, score scaling, validation, and export. Every
step should be reproducible and explainable.

## Design Goals

- Store the original input data as a content-addressed snapshot.
- Represent the model build as a branching tree of steps.
- Record every step's parameters, parent step ids, input artifacts, output
  artifacts, metrics, timestamps, and code version.
- Allow a user to go back to any node, change a parameter, and replay only that
  node's downstream branch.
- Preserve old runs instead of mutating history, so auditability is never lost.
- Keep scorecard logic separate from the GUI.

## Branching Pathway

The pathway is a tree/DAG rather than a single linear script. Multiple child
steps can share the same parent, allowing side-by-side options such as:

```text
input data
  -> profile
      -> automatic binning
          -> scorecard A
      -> manual binning
          -> scorecard B
```

If the manual binning parameters change, Cardre keeps the original profile and
automatic-binning branch, then regenerates only the manual-binning branch and
its descendants. This is intended to feel like PowerBI's transform-data flow,
but with model-building audit records.

## Current Scaffold

The new active code lives under `cardre/`:

- `cardre/store.py` stores datasets and artifacts by hash.
- `cardre/audit.py` defines JSON-serialisable artifact and step records.
- `cardre/pipeline.py` defines branching plans, runs, and replay semantics.

The older prototype files at the repo root are retained temporarily as reference
material while the project is rebuilt around the new architecture.

## Near-Term Roadmap

1. Add pure data profiling and target validation steps.
2. Add fine-classing and WOE/IV steps as pipeline nodes.
3. Add branch comparison for competing binning/model choices.
4. Add a Streamlit GUI that edits pathway nodes and replays branches.
5. Add exportable audit packs for model governance.

See `docs/plans/cardre-application-plan.md` for the end-to-end application plan.
See `docs/plans/phase-1-execution-plan.md` for the current Phase 1 build plan.
See `docs/plans/phase-1-technical-implementation-plan.md` for the execution-ready
technical plan.
