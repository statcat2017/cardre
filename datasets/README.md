# Cardre bundled sample datasets

Sample credit-risk datasets you can load into cardre to start
experimenting immediately. Each dataset lives in its own subdirectory with
the CSV, a `.parquet` twin, a `README.md` describing the columns, a
`LICENSE.txt`, and a `CITATION.txt`.

Both datasets are licensed CC BY 4.0, which permits redistribution
provided you give attribution. Keep the `CITATION.txt` and `LICENSE.txt`
files with the data.

## Supported workflow

Cardre's import boundary accepts **Parquet only** (see
`docs/plans/one-cardre-purge-plan.md` and
`cardre/nodes/prep/import_.py`). Point the import step at the committed
Parquet twin of each dataset:

```
datasets/german_credit/german_credit.parquet
datasets/taiwan_credit_default/taiwan_credit_default.parquet
```

The `*.csv` files are the licensed source-of-truth data kept for
attribution and portability. The `.parquet` twins are generated from them
by a maintained script:

```bash
python3 scripts/convert_sample_datasets_to_parquet.py
```

Run the script from the repo root to regenerate the Parquet files from the
current CSVs (for example after updating a dataset). It is idempotent and
never modifies the CSV source files.

## Datasets

| Dataset | Rows × Cols | CSV size | Parquet size | Target | License |
|---|---|---|---|---|---|
| [Statlog German Credit](german_credit/) | 1000 × 21 | 83 KB | 24 KB | `class` (good/bad) | CC BY 4.0 |
| [Default of Credit Card Clients](taiwan_credit_default/) | 30000 × 24 | 2.6 MB | 1.6 MB | `default payment next month` (0/1) | CC BY 4.0 |

## Which one to start with

- **German Credit** — the canonical teaching set. Small, fast, mix of
  categorical and numerical features, and ships with a 2×2 cost matrix
  (false positives cost 5×). Good for a first walkthrough of the
  scorecard pathway: profiling → binning → WOE/IV → logistic regression →
  score scaling → validation.
- **Default of Credit Card Clients** — a larger, real-world PD dataset.
  30k rows of behavioural payment-history features. Good for
  train/test/OOT splitting and validation on a non-trivial sample.

## Attribution

Both datasets are © their respective authors, licensed under CC BY 4.0.
See each dataset's `CITATION.txt` for the full citation and
`LICENSE.txt` for the full license terms. The CC BY 4.0 license requires
that you retain these attribution files if you redistribute the datasets
or any derived work.