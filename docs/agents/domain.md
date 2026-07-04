# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root.
- **`docs/adr/`** — read ADRs that touch the area being triaged or implemented.

If any of these files don't exist, proceed silently. Don't flag their absence or suggest creating them upfront.

## File structure

This is a single-context repo: one root `CONTEXT.md` plus root `docs/adr/`.

## Use the glossary's vocabulary

When output names a domain concept, use the term as defined in `CONTEXT.md`.

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly rather than silently overriding it.
