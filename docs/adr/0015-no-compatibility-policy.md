# ADR 0015 — Pre-launch no-compatibility policy (generalizes and supersedes ADR 0003)

## Status

Accepted

## Supersedes

[ADR 0003 — Pre-launch persisted-plan compatibility policy](0003-no-legacy-plan-accommodation.md). ADR 0003 records the original OptBinning decision; this ADR generalizes that policy to the whole persisted surface and remains the active policy.

## Decision

Until Cardre's first production release, only the current persisted plan, node,
evidence and artifact formats are supported. No aliases, fallback readers,
compatibility shims or migrations for previous development formats may be added.

## Context

ADR 0003 established that Cardre may freely break persisted-plan compatibility
because it has never been deployed and no persisted plans exist outside developer
machines. The same reasoning applies to the entire persisted surface — plan steps,
node contracts, evidence identities, and artifact schemas. Backward compatibility
with previous development formats is not a constraint, and maintaining it would
only add dead code surface that defends against a state that does not exist.

## Considered Options

- **Maintain backward compatibility**: keep alias readers, fallback matchers and
  permissive constructors for earlier development formats. Costs complexity and
  code surface defending against states that do not exist.

- **Drop backward compatibility entirely** (chosen): keep exactly one current
  shape per persisted concept, reject anything else. Simpler code, clearer intent,
  no dead compat branches.

## Consequences

- Plan step, node, evidence and artifact formats may change without migration
  code or additive-only constraints.
- Compatibility shims, fallback readers, alias re-exports and historical
  identifier blacklists must not be introduced.
- This ADR should be revisited when Cardre reaches its first real deployment;
  future changes must then adopt a compatibility or migration strategy recorded
  in a new ADR.
