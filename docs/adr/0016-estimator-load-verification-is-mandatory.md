# ADR 0016 — Estimator load verification is mandatory

## Status

Accepted

## Decision

There is one load path for a serialized estimator (joblib binary) Artifact:
resolve the estimator reference via `InputCollection.artifact_ref`, read the
bytes, **verify** the published `logical_hash` against the bytes' SHA-256, and
**require** `creating_run_id` metadata before deserialising. Refusing to load
untrusted binaries is the only trust policy — there is no "unverified" or
"skip-hash-check" load path, on any stream.

## Context

Estimators are published as two Artifacts sharing one descriptor family: a
parseable JSON `model` and a joblib `estimator` binary (see the *Estimator
Reference* section of `CONTEXT.md`). The JSON model cites the binary's
descriptor id, `physical_hash` and `logical_hash` before the binary is staged,
so downstream consumers resolve the binary by reference at load time.

Before this decision, the two load sites diverged on trust:

- `cardre/nodes/explainability.py` (`_load_estimator`) verified the hash and
  required `creating_run_id`, refusing untrusted binaries.
- `cardre/nodes/validate/apply.py` (`_load_estimator` and
  `_apply_runtime_calibration`) resolved the reference and deserialised with
  **no** verification.

The validate stream — which scores `test` and `oot` holdout samples — was the
*less* suspicious of the two. That asymmetry had no recorded rationale; the
validate stream was trusting binaries the build stream had just produced,
rather than verifying them.

Consolidating the three hand-rolled publish dances and the divergent loaders
behind one deep module (the model-Artifact publication/load seam) forced an
explicit choice: preserve the asymmetry as an optional `trust` parameter, or
make verification mandatory everywhere. This ADR records that choice.

## Considered Options

- **Optional verification** (`trust: "verified" | "unverified"`): each caller
  declares its policy. Preserves the current behaviour exactly and keeps the
  validate stream's load cheaper. Keeps the policy split alive at the
  interface, so the trust level becomes a per-call fact every caller must
  remember to set correctly.

- **Mandatory verification** (chosen): the deep load module always verifies
  the hash and requires `creating_run_id`; there is no unverified path. The
  validate stream gains the tamper check it was missing. Adds a hash computation
  per loaded binary on the validate stream (negligible relative to the
  `joblib.load` and the scoring it precedes) and removes the option to skip it.

The mandatory option was chosen because scoring holdouts with a tampered or
untrusted binary is at least as consequential as explaining one, and the
validate stream's prior lack of verification had no recorded reason to differ
from the explainability stream. ADR-0014's "enforceable node contracts" spirit
leans toward a single, closed trust policy over a per-call flag.

## Consequences

- The single estimator-load module owns the trust policy; callers cannot opt
  out. A future node that needs an unverified load must reopen this ADR.
- `cardre/nodes/validate/apply.py` gains hash verification + `creating_run_id`
  enforcement on both its estimator load and its runtime-calibrator load. Any
  test fixture that stages a binary without `creating_run_id` metadata will
  now fail to load and must be updated to carry the metadata.
- The publish side is unchanged: the JSON-must-precede-bytes ordering and the
  `creating_run_id`-on-publish requirement already hold and are recorded in
  `CONTEXT.md`.
- This ADR should be revisited if a legitimate unverified-load need appears
  (e.g. loading a third-party estimator with no provenance metadata); the
  resolution must be recorded in a new ADR.