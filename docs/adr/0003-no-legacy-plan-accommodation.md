# ADR 0003 — Pre-launch persisted-plan compatibility policy

## Status

Accepted

## Decision

Until Cardre's first production release, only the current persisted plan, node,
evidence and artifact formats are supported. No aliases, fallback readers,
compatibility shims or migrations for previous development formats may be added.

## Context

Cardre has never been deployed, so no persisted plans exist outside developer
machines. Backward compatibility with previous development formats is therefore
not a constraint, and maintaining it would only add dead code surface that
defends against a state that does not exist.

## Consequences

- Node types, step ids, canonical step ids, params, and artifact shapes may
  change without migration code or additive-only constraints.
- Compatibility shims, fallback readers, alias re-exports and historical
  identifier blacklists must not be introduced.
- This ADR should be revisited when Cardre reaches its first real deployment;
  future changes must then adopt a compatibility or migration strategy recorded
  in a new ADR.
