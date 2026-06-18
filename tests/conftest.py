"""Shared pytest fixtures for the cardre test suite."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from cardre.store import ProjectStore


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "reference_scorecard_r_german_credit"


def _load_golden_csvs() -> dict[str, pl.DataFrame]:
    """Load all CSV golden fixture files into Polars DataFrames."""
    result: dict[str, pl.DataFrame] = {}
    for csv_path in sorted(GOLDEN_DIR.glob("*.csv")):
        name = csv_path.stem
        result[name] = pl.read_csv(
            csv_path,
            infer_schema_length=0,
            null_values=["", "NA"],
            truncate_ragged_lines=True,
        )
    return result


def _load_golden_jsons() -> dict[str, object]:
    """Load all JSON golden fixture files."""
    import json
    result: dict[str, object] = {}
    for json_path in sorted(GOLDEN_DIR.glob("*.json")):
        name = json_path.stem
        result[name] = json.loads(json_path.read_text())
    return result


# ---------------------------------------------------------------------------
# R → Cardre column name mapping
# ---------------------------------------------------------------------------

R_TO_CARDRE: dict[str, str] = {
    "status.of.existing.checking.account": "checking_account_status",
    "duration.in.month": "duration_months",
    "credit.history": "credit_history",
    "purpose": "purpose",
    "credit.amount": "credit_amount",
    "savings.account.and.bonds": "savings_account_bonds",
    "present.employment.since": "present_employment_since",
    "installment.rate.in.percentage.of.disposable.income": "installment_rate_percent_disposable_income",
    "other.debtors.or.guarantors": "other_debtors_guarantors",
    "property": "property",
    "age.in.years": "age_years",
    "other.installment.plans": "other_installment_plans",
    "housing": "housing",
    "creditability": "credit_risk_class",
}

CARDRE_TO_R: dict[str, str] = {v: k for k, v in R_TO_CARDRE.items()}

R_FILTERED_COLUMNS: list[str] = [
    "status.of.existing.checking.account",
    "duration.in.month",
    "credit.history",
    "purpose",
    "credit.amount",
    "savings.account.and.bonds",
    "present.employment.since",
    "installment.rate.in.percentage.of.disposable.income",
    "other.debtors.or.guarantors",
    "property",
    "age.in.years",
    "other.installment.plans",
    "housing",
]

R_SELECTED_VARS_DOT: list[str] = [
    "status.of.existing.checking.account",
    "duration.in.month",
    "credit.history",
    "purpose",
    "credit.amount",
    "savings.account.and.bonds",
    "installment.rate.in.percentage.of.disposable.income",
    "age.in.years",
    "other.installment.plans",
    "housing",
]

R_DROPPED_VARS_DOT: list[str] = [
    "present.employment.since",
    "other.debtors.or.guarantors",
    "property",
]

R_EXCLUDE_VARS_DOT: list[str] = [
    "personal_status_sex",
    "present_residence_since",
    "existing_credits_at_bank",
    "job",
    "people_liable_maintenance",
    "telephone",
    "foreign_worker",
]

CARDRE_EXCLUDE: list[str] = [
    "personal_status_sex",
    "present_residence_since",
    "existing_credits_at_bank",
    "job",
    "people_liable_maintenance",
    "telephone",
    "foreign_worker",
]

R_SCORECARD_PARAMS: dict[str, object] = {
    "base_score": 600,
    "base_odds": "19:1",
    "points_to_double_odds": 50,
    "higher_score_is_lower_risk": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def r_col(r_name: str) -> str:
    """Translate R dot-name to Cardre underscore-name."""
    return R_TO_CARDRE.get(r_name, r_name)


def r_woe_col(r_woe_name: str) -> str:
    """Translate R ``status.of.existing.checking.account_woe`` to Cardre
    ``checking_account_status_woe``."""
    base = r_woe_name.replace("_woe", "")
    return r_col(base) + "_woe"


def r_woe_list(r_feature_names: list[str]) -> list[str]:
    """Translate a list of R feature names (without _woe suffix) to Cardre
    _woe column names."""
    return [r_woe_col(f + "_woe") for f in r_feature_names]


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    """Create an isolated ProjectStore in a temp directory."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    s = ProjectStore(tmp / "test.cardre")
    s.initialize()
    return s


@pytest.fixture(scope="session")
def golden_csv() -> dict[str, pl.DataFrame]:
    """Load all CSV golden fixtures into Polars DataFrames.

    Keys: ``filtered_data``, ``bins_adj``, ``scorecard``, ``train_raw``,
    ``test_raw``, ``train_woe``, ``test_woe``, ``train_scores``, ``test_scores``,
    ``model_coefficients``, ``selected_terms``, ``psi``.
    """
    return _load_golden_csvs()


@pytest.fixture(scope="session")
def golden_json() -> dict[str, object]:
    """Load all JSON golden fixtures.

    Keys: ``bins_adj``, ``scorecard``, ``psi``, ``metadata``.
    """
    return _load_golden_jsons()


@pytest.fixture(scope="session")
def golden_metadata() -> dict:
    """Convenience fixture returning just the metadata dict."""
    import json
    return json.loads((GOLDEN_DIR / "metadata.json").read_text())


@pytest.fixture(scope="session")
def golden_raw_data() -> Path:
    """Return path to the UCI-format ``german.data`` fixture."""
    return GOLDEN_DIR / "german.data"


@pytest.fixture
def client():
    """FastAPI TestClient bound to the sidecar app."""
    from fastapi.testclient import TestClient
    from sidecar.main import app
    return TestClient(app)


@pytest.fixture
def bare_app():
    """Raw FastAPI app instance (for dependency overrides, etc.)."""
    from sidecar.main import app
    return app


@pytest.fixture
def _isolated_registry(tmp_path, monkeypatch):
    """Isolate the project registry to a temp path.

    Apply with ``pytest.mark.usefixtures("_isolated_registry")`` or
    ``pytestmark = pytest.mark.usefixtures("_isolated_registry")``.
    """
    registry = tmp_path / "registry" / "projects.json"
    monkeypatch.setenv("CARDRE_REGISTRY_PATH", str(registry))
