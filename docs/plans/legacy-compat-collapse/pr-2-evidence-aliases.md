# PR 2 — Remove evidence compat aliases and orphaned `RUN_MANIFEST` kind

**Sprint:** `docs/plans/legacy-compat-collapse.md`
**Depends on:** PR 1
**Risk:** Low
**Authority:** ADR 0003.

## Goal

Delete the dead compat-alias enum members, schema constants, the `LegacyEvidenceCompatibilityError` exception (no raiser), and the orphaned `RUN_MANIFEST` evidence path (kind + adapter + profile + `RunManifestEvidence` model — no caller). Update the 3 callers of the compat-alias schema constants to use the canonical names.

## Files to read first (do not edit)

- `cardre/_evidence/kinds.py` — `WOE_APPLICATION_EVIDENCE` (:33), `SCORE_APPLICATION_EVIDENCE` (:35), `RUN_MANIFEST` (:38), `LegacyEvidenceCompatibilityError` (:66-67).
- `cardre/_evidence/schemas.py` — `SCHEMA_WOE_APPLICATION_EVIDENCE` (:28), `SCHEMA_SCORE_APPLICATION_EVIDENCE` (:30), `SCHEMA_RUN_MANIFEST` (:33).
- `cardre/_evidence/profiles.py` — `RUN_MANIFEST` profile (:223-228).
- `cardre/_evidence/adapters/__init__.py` — `RUN_MANIFEST` adapter (:158-161); `RunManifestEvidence` import (:45).
- `cardre/_evidence/models/manifest.py` — `RunManifestEvidence` (:53-87).
- `cardre/_evidence/models/__init__.py` — exports `RunManifestEvidence` (:40, :104).
- Callers of compat-alias constants:
  - `cardre/modeling/adapters.py:26,71,84` — `SCHEMA_SCORE_APPLICATION_EVIDENCE`.
  - `cardre/nodes/validate/apply.py:12,207,223` — `SCHEMA_WOE_APPLICATION_EVIDENCE`.
  - `cardre/nodes/validate/analyse.py:17,211` — `SCHEMA_SCORE_APPLICATION_EVIDENCE`.
- `tests/test_evidence_adapters.py` — `RUN_MANIFEST` adapter test at :234; banned-import guard at :66.

## Code instructions

### Step 1 — Remove compat-alias enum members and exception

In `cardre/_evidence/kinds.py`, delete:
- Line 33: `WOE_APPLICATION_EVIDENCE = "apply_woe_evidence"  # compat alias`
- Line 35: `SCORE_APPLICATION_EVIDENCE = "apply_model_evidence"  # compat alias`
- Line 38: `RUN_MANIFEST = "run_manifest"`
- Lines 66-67: `class LegacyEvidenceCompatibilityError(EvidenceSchemaError):` and its docstring `"""Legacy payload matched only via compatibility heuristics."""`

### Step 2 — Remove compat-alias schema constants

In `cardre/_evidence/schemas.py`, delete:
- Line 28: `SCHEMA_WOE_APPLICATION_EVIDENCE = SCHEMA_APPLY_WOE_EVIDENCE  # compat alias`
- Line 30: `SCHEMA_SCORE_APPLICATION_EVIDENCE = SCHEMA_APPLY_MODEL_EVIDENCE  # compat alias`
- Line 33: `SCHEMA_RUN_MANIFEST = "cardre.run_manifest.v1"`

### Step 3 — Remove the `RUN_MANIFEST` profile

In `cardre/_evidence/profiles.py`, delete the `RUN_MANIFEST` profile entry (lines 223-228) and any import of `SCHEMA_RUN_MANIFEST` (check the imports at the top of the file).

### Step 4 — Remove the `RUN_MANIFEST` adapter

In `cardre/_evidence/adapters/__init__.py`:
- Delete the `RUN_MANIFEST` adapter entry (lines 158-161).
- Remove `RunManifestEvidence` from the import at line 45.

### Step 5 — Remove `RunManifestEvidence` model

In `cardre/_evidence/models/manifest.py`, delete the `RunManifestEvidence` class (lines 53-87).

In `cardre/_evidence/models/__init__.py`, remove `RunManifestEvidence` from:
- The import (line 40).
- `__all__` (line 104).

### Step 6 — Update callers of compat-alias constants

Replace each removed constant with its canonical name:

- `cardre/modeling/adapters.py`:
  - Line 26: `from cardre._evidence.schemas import SCHEMA_SCORE_APPLICATION_EVIDENCE` → `from cardre._evidence.schemas import SCHEMA_APPLY_MODEL_EVIDENCE`
  - Lines 71, 84: `SCHEMA_SCORE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_MODEL_EVIDENCE`
- `cardre/nodes/validate/apply.py`:
  - Line 12: `SCHEMA_WOE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_WOE_EVIDENCE`
  - Lines 207, 223: `SCHEMA_WOE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_WOE_EVIDENCE`
- `cardre/nodes/validate/analyse.py`:
  - Line 17: `SCHEMA_SCORE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_MODEL_EVIDENCE`
  - Line 211: `SCHEMA_SCORE_APPLICATION_EVIDENCE` → `SCHEMA_APPLY_MODEL_EVIDENCE`

Verify:
```bash
rg -n "WOE_APPLICATION_EVIDENCE|SCORE_APPLICATION_EVIDENCE|SCHEMA_WOE_APPLICATION|SCHEMA_SCORE_APPLICATION|RUN_MANIFEST|RunManifestEvidence|LegacyEvidenceCompatibilityError" cardre/
# Zero matches.
```

### Step 7 — Update tests

- `tests/test_evidence_adapters.py`: delete the `RUN_MANIFEST` adapter test at line 234 (the tuple `(EvidenceKind.RUN_MANIFEST, "run_manifest", "audit", ...)` in the parametrize list). If other tests reference the removed kinds/aliases, delete those assertions.
- Extend the banned-import guard test (near line 66) to also assert the removed identifiers are absent from `cardre/` source:
  ```python
  def test_no_compat_aliases_in_source():
      import subprocess
      banned = [
          "WOE_APPLICATION_EVIDENCE", "SCORE_APPLICATION_EVIDENCE",
          "SCHEMA_WOE_APPLICATION_EVIDENCE", "SCHEMA_SCORE_APPLICATION_EVIDENCE",
          "LegacyEvidenceCompatibilityError", "SCHEMA_RUN_MANIFEST",
          "EvidenceKind.RUN_MANIFEST", "RunManifestEvidence",
      ]
      result = subprocess.run(
          ["rg", "-n", "|".join(banned), "cardre/"],
          capture_output=True, text=True,
      )
      assert result.returncode != 0, f"Banned compat identifiers still in source:\n{result.stdout}"
  ```

## Verification

```bash
. .venv/bin/activate
rg -n "WOE_APPLICATION_EVIDENCE|SCORE_APPLICATION_EVIDENCE|SCHEMA_WOE_APPLICATION|SCHEMA_SCORE_APPLICATION|RUN_MANIFEST|RunManifestEvidence|LegacyEvidenceCompatibilityError" cardre/
# Zero matches in cardre/.
ruff check --fix
pytest tests/test_evidence_adapters.py tests/test_evidence_reader.py \
       tests/test_evidence_profiles.py tests/test_canonical_contract.py -q
make preflight
scripts/pr-gate.sh
```

## Definition of done

- [ ] `WOE_APPLICATION_EVIDENCE`, `SCORE_APPLICATION_EVIDENCE`, `RUN_MANIFEST` enum members gone.
- [ ] `SCHEMA_WOE_APPLICATION_EVIDENCE`, `SCHEMA_SCORE_APPLICATION_EVIDENCE`, `SCHEMA_RUN_MANIFEST` constants gone.
- [ ] `LegacyEvidenceCompatibilityError` class gone.
- [ ] `RUN_MANIFEST` profile + adapter + `RunManifestEvidence` model gone.
- [ ] All callers use canonical `SCHEMA_APPLY_WOE_EVIDENCE` / `SCHEMA_APPLY_MODEL_EVIDENCE`.
- [ ] Guard test asserts the removed identifiers are absent from `cardre/`.
- [ ] `ruff check` clean; `make preflight` green; PR gate green.

## Failure mode

- **Import error in `adapters.py`/`apply.py`/`analyse.py`:** you missed a caller of a removed constant. Grep: `rg -n "SCHEMA_WOE_APPLICATION|SCHEMA_SCORE_APPLICATION" cardre/`. Replace with the canonical name.
- **`test_evidence_adapters.py` parametrize error:** the `RUN_MANIFEST` tuple is still in the parametrize list. Delete the whole tuple.
- **`EvidenceKind.RUN_MANIFEST` import in a test:** delete the import and the test that uses it.