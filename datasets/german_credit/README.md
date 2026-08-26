# Statlog (German Credit Data)

A small, famous credit-risk teaching dataset. 1000 loan applicants, 20
features (7 numerical, 13 categorical), one binary target. Ships with a
2×2 cost matrix.

- **Source**: UCI Machine Learning Repository #144
- **URL**: https://archive.ics.uci.edu/dataset/144/statlog+german+credit+data
- **DOI**: https://doi.org/10.24432/C5NC77
- **Author**: Hans Hofmann, University of Hamburg (1994)
- **License**: CC BY 4.0 (see `LICENSE.txt`)
- **Citation**: see `CITATION.txt`
- **File**: `german_credit.parquet` (generated from `german_credit.csv`, UTF-8, comma-separated, 1000 rows × 21 columns, ~83 KB CSV / ~24 KB Parquet)

## Cardre on-ramp

- **Target column**: `class`
- **Good value**: `good` (700 rows, 70%)
- **Bad value**: `bad` (300 rows, 30%)
- Point the import step at the committed `german_credit.parquet` file; the
  Parquet twin is regenerated from the CSV by
  `scripts/convert_sample_datasets_to_parquet.py`.

## Columns

The original UCI file has no header and uses opaque codes (A11, A30,
...). This bundle adds a descriptive header row. Column order matches
the original `german.data`; values are unchanged.

| # | Column | Type | Values / range |
|---|---|---|---|
| 1 | `checking_account_status` | cat | A11 `<0 DM`, A12 `0..200 DM`, A13 `>=200 DM`, A14 no account |
| 2 | `duration_months` | int | 4–72 |
| 3 | `credit_history` | cat | A30–A34 |
| 4 | `purpose` | cat | A40–A410 |
| 5 | `credit_amount` | int | DM amount |
| 6 | `savings_account` | cat | A61–A65 |
| 7 | `present_employment_since` | cat | A71–A75 |
| 8 | `installment_rate_pct` | int | % of disposable income |
| 9 | `personal_status_sex` | cat | A91–A95 |
| 10 | `other_debtors` | cat | A101–A103 |
| 11 | `present_residence_since` | int | years |
| 12 | `property` | cat | A121–A124 |
| 13 | `age_years` | int | 19–75 |
| 14 | `other_installment_plans` | cat | A141–A143 |
| 15 | `housing` | cat | A151–A153 |
| 16 | `num_existing_credits` | int | at this bank |
| 17 | `job` | cat | A171–A174 |
| 18 | `num_dependents` | int | people liable for maintenance |
| 19 | `telephone` | cat | A191 none, A192 registered |
| 20 | `foreign_worker` | cat | A201 yes, A202 no |
| 21 | `class` | target | `good` / `bad` |

### Value-code reference

The codes above (A11, A30, ...) are defined in the original `german.doc`
file. The full code map:

**Attribute 1 — Status of existing checking account**
- `A11`: `< 0 DM`
- `A12`: `0 <= ... < 200 DM`
- `A13`: `>= 200 DM / salary assignments for at least 1 year`
- `A14`: no checking account

**Attribute 3 — Credit history**
- `A30`: no credits taken / all credits paid back duly
- `A31`: all credits at this bank paid back duly
- `A32`: existing credits paid back duly till now
- `A33`: delay in paying off in the past
- `A34`: critical account / other credits existing (not at this bank)

**Attribute 4 — Purpose**
- `A40`: car (new), `A41`: car (used), `A42`: furniture/equipment,
  `A43`: radio/television, `A44`: domestic appliances, `A45`: repairs,
  `A46`: education, `A47`: vacation (does not exist), `A48`: retraining,
  `A49`: business, `A410`: others

**Attribute 6 — Savings account/bonds**
- `A61`: `< 100 DM`, `A62`: `100..500 DM`, `A63`: `500..1000 DM`,
  `A64`: `>= 1000 DM`, `A65`: unknown / no savings account

**Attribute 7 — Present employment since**
- `A71`: unemployed, `A72`: `< 1 year`, `A73`: `1..4 years`,
  `A74`: `4..7 years`, `A75`: `>= 7 years`

**Attribute 9 — Personal status and sex**
- `A91`: male divorced/separated, `A92`: female divorced/separated/married,
  `A93`: male single, `A94`: male married/widowed, `A95`: female single

**Attribute 10 — Other debtors / guarantors**
- `A101`: none, `A102`: co-applicant, `A103`: guarantor

**Attribute 12 — Property**
- `A121`: real estate, `A122`: building society savings agreement / life
  insurance, `A123`: car or other (not in attr 6), `A124`: unknown / no property

**Attribute 14 — Other installment plans**
- `A141`: bank, `A142`: stores, `A143`: none

**Attribute 15 — Housing**
- `A151`: rent, `A152`: own, `A153`: for free

**Attribute 17 — Job**
- `A171`: unemployed/unskilled non-resident, `A172`: unskilled resident,
  `A173`: skilled employee/official, `A174`: management/self-employed/highly qualified

**Attribute 19 — Telephone**
- `A191`: none, `A192`: yes, registered under the customer's name

**Attribute 20 — Foreign worker**
- `A201`: yes, `A202`: no

## Cost matrix

The dataset is designed to be used with a 2×2 cost matrix. Rows are the
actual class; columns are the predicted class. `1 = good`, `2 = bad`.

```
          Predicted
          good  bad
Actual good   0    1
       bad    5    0
```

It is 5× worse to classify a bad customer as good (extend credit to a
defaulter) than to classify a good customer as bad (turn away a good
applicant).

## Changes from the original UCI distribution

See `LICENSE.txt` for the full list. In short: header row added,
target mapped from `{1, 2}` to `{"good", "bad"}`, file renamed. Column
values are otherwise unchanged.