# Phase Plan: Make CI Quality Gates Blocking

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Python ruff fixes + pl bug | Run `ruff check --fix`, add `NoopNode`/`AutoBinningFitNode` to `__all__`, add `pl` TYPE_CHECKING import in `audit.py`. Verify `ruff check` passes and `pytest` stays green. |
| 2 | Frontend semantic fixes + pin-down tests | Fix 4 React hook anti-patterns (setState-in-effect, immutability, exhaustive-deps), replace 30 `any` with proper types, remove 17 unused imports/vars. Write pin-down tests before refactoring. Verify `npm run lint`, `npx tsc --noEmit`, `npm test` all pass. |
| 3 | Prettier formatting + .prettierignore | Add `frontend/.prettierignore` excluding generated API files, run `prettier --write src/`. Verify `npm run format:check` passes. |
| 4 | CI + contributor docs | Remove `continue-on-error` from Ruff/ESLint/Prettier steps in `ci.yml`. Update `CONTRIBUTING.md` with full blocking command set. |
