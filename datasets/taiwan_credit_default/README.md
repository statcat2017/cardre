# Default of Credit Card Clients (Yeh, 2009)

A larger, real-world PD (probability of default) dataset. 30,000
credit-card clients in Taiwan (Apr–Sep 2005), 23 features — credit limit,
demographics, and 6 months of repayment status, bill statements, and
previous payments — plus one binary target.

- **Source**: UCI Machine Learning Repository #350
- **URL**: https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients
- **DOI**: https://doi.org/10.24432/C55S3H
- **Author**: I-Cheng Yeh (2009)
- **License**: CC BY 4.0 (see `LICENSE.txt`)
- **Citation**: see `CITATION.txt`
- **File**: `taiwan_credit_default.parquet` (generated from `taiwan_credit_default.csv`, UTF-8, comma-separated, 30000 rows × 24 columns, ~2.6 MB CSV / ~1.6 MB Parquet)

## Cardre on-ramp

- **Target column**: `default payment next month`
- **Good value**: `0` (no default; 23364 rows, 77.88%)
- **Bad value**: `1` (default; 6636 rows, 22.12%)
- Point the import step at the committed `taiwan_credit_default.parquet`
  file; the Parquet twin is regenerated from the CSV by
  `scripts/convert_sample_datasets_to_parquet.py`.
- 30k rows is enough that train/test/OOT split and validation metrics are
  meaningful.

## Columns

| Column | Type | Description |
|---|---|---|
| `LIMIT_BAL` | int | Credit limit (NT$, New Taiwan dollars) |
| `SEX` | cat | 1 = male, 2 = female |
| `EDUCATION` | cat | 1 = graduate school, 2 = university, 3 = high school, 4 = others |
| `MARRIAGE` | cat | 1 = married, 2 = single, 3 = others |
| `AGE` | int | Age in years |
| `PAY_0` | cat | Repayment status in Sep 2005 |
| `PAY_2` | cat | Repayment status in Aug 2005 |
| `PAY_3` | cat | Repayment status in Jul 2005 |
| `PAY_4` | cat | Repayment status in Jun 2005 |
| `PAY_5` | cat | Repayment status in May 2005 |
| `PAY_6` | cat | Repayment status in Apr 2005 |
| `BILL_AMT1` | int | Bill statement amount in Sep 2005 (NT$) |
| `BILL_AMT2` | int | Bill statement amount in Aug 2005 (NT$) |
| `BILL_AMT3` | int | Bill statement amount in Jul 2005 (NT$) |
| `BILL_AMT4` | int | Bill statement amount in Jun 2005 (NT$) |
| `BILL_AMT5` | int | Bill statement amount in May 2005 (NT$) |
| `BILL_AMT6` | int | Bill statement amount in Apr 2005 (NT$) |
| `PAY_AMT1` | int | Previous payment amount in Sep 2005 (NT$) |
| `PAY_AMT2` | int | Previous payment amount in Aug 2005 (NT$) |
| `PAY_AMT3` | int | Previous payment amount in Jul 2005 (NT$) |
| `PAY_AMT4` | int | Previous payment amount in Jun 2005 (NT$) |
| `PAY_AMT5` | int | Previous payment amount in May 2005 (NT$) |
| `PAY_AMT6` | int | Previous payment amount in Apr 2005 (NT$) |
| `default payment next month` | target | 1 = yes (default), 0 = no |

### Repayment status code (`PAY_0`..`PAY_6`)

- `-1` = pay duly
- `1` = payment delay for one month
- `2` = payment delay for two months
- ...
- `9` = payment delay for nine months or more

## Changes from the original UCI distribution

See `LICENSE.txt` for the full list. In short: Excel converted to CSV,
`ID` column dropped, descriptive column names retained, values unchanged.