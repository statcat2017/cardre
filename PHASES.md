# Phase Plan — Deferred Node Exposure

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Registry availability + error classes | Add `NodeAvailability` dataclass, `_probe_optional_dep`, `availability()`/`is_available()` to `NodeRegistry`; add `OptionalDependencyNotInstalled` and `PlanContainsUnavailableNodesError` to `cardre/errors.py` |
| 2 | Node optional_deps + pre-execution gate | Set `optional_dependencies` class attr on boosting/smote/explainability nodes; add `validate_plan_executability` to `PlanExecutor`; call it in `RunService.run_plan` before `create_run` |
| 3 | API model + route changes | Extend `NodeTypeItem` and `NodeTypeSchemaResponse` with `available`, `disabled_reason`, `missing_optional_dependencies`; update `list_node_types` and `get_node_type_schema` to populate them; add `?available_only=true` query param |
| 4 | Frontend + OpenAPI regen | Extend `SafeSchema` with `available`/`disabled_reason`; render disabled banner in `SchemaDrivenParamsEditor`; regenerate `openapi.json` and `schema.d.ts` |
| 5 | Docs + final verification | Update `AGENTS.md` error codes; run full test suite; create PR |
