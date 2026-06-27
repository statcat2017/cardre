from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

_GERMAN_COLS_STR = {
    c: "str" for c in [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
}


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_german_credit(tmp_dir):
    p = tmp_dir / "german_credit.csv"
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    header = ",".join(columns)
    rows = [
        "A11,6,A34,A43,1169,A65,A75,4,A93,A101,4,A121,67,A143,A152,2,A173,1,A192,A201,1",
        "A12,24,A32,A43,5951,A61,A73,2,A92,A101,4,A121,22,A142,A152,2,A173,1,A191,A201,2",
    ]
    p.write_text("\n".join([header] + rows))
    return p


@pytest.fixture
def larger_german_credit(tmp_dir):
    p = tmp_dir / "german_credit.csv"
    columns = [
        "checking_account_status", "duration_months", "credit_history", "purpose",
        "credit_amount", "savings_account_bonds", "present_employment_since",
        "installment_rate_percent_disposable_income", "personal_status_sex",
        "other_debtors_guarantors", "present_residence_since", "property",
        "age_years", "other_installment_plans", "housing",
        "existing_credits_at_bank", "job", "people_liable_maintenance",
        "telephone", "foreign_worker", "credit_risk_class",
    ]
    good = "A11,6,A34,A43,1169,A65,A75,4,A93,A101,4,A121,67,A143,A152,2,A173,1,A192,A201,1"
    bad = "A12,24,A32,A43,5951,A61,A73,2,A92,A101,4,A121,22,A142,A152,2,A173,1,A191,A201,2"
    lines = [",".join(columns)]
    for i in range(50):
        parts_g = good.split(",")
        parts_g[0] = f"A{i % 11 + 11}"
        parts_g[1] = str(6 + (i % 48))
        parts_g[4] = str(1000 + i * 100)
        parts_g[10] = str(i % 4 + 1)
        parts_g[12] = str(20 + (i % 60))
        lines.append(",".join(parts_g))

        parts_b = bad.split(",")
        parts_b[0] = f"A{i % 11 + 11}"
        parts_b[1] = str(12 + (i % 36))
        parts_b[4] = str(2000 + i * 200)
        parts_b[10] = str(i % 4 + 1)
        parts_b[12] = str(25 + (i % 55))
        lines.append(",".join(parts_b))

    p.write_text("\n".join(lines))
    return p
