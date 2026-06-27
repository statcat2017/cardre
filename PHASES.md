# Phase Plan — Reduce structural debt in Cardre seams

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Split test_sidecar_api.py | Create `tests/test_sidecar_api/` package with conftest + 12 route-domain modules; delete monolith |
| 2 | Executor error-classification tests | Add parametrized characterization test for all 10 error categories in `_CATEGORY_MAP`/`_CODE_MAP` |
| 3 | Update line-count guard | Remove stale `tests/test_sidecar_api.py` debt entry from `LINE_COUNT_DEBT` |
| 4 | Verify + PR | Run full test suite + line-count guard; raise single PR |
