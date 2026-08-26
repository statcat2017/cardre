#!/usr/bin/env python3
"""Generate the bundled sample-dataset Parquet variants from the licensed CSVs.

Cardre's import boundary accepts Parquet only. The source-of-truth datasets in
``datasets/`` are distributed as CSV (kept for attribution and portability);
this script produces the committed ``.parquet`` twin of each CSV so users can
point the import step at a supported file without any manual conversion.

Run from the repo root:

    python3 scripts/convert_sample_datasets_to_parquet.py

The script is idempotent: it regenerates the Parquet files from the current
CSVs. It does not delete or modify the licensed CSV source files.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parent.parent

DATASETS: dict[str, str] = {
    "german_credit/german_credit.csv": "german_credit/german_credit.parquet",
    "taiwan_credit_default/taiwan_credit_default.csv": (
        "taiwan_credit_default/taiwan_credit_default.parquet"
    ),
}


def main() -> int:
    for csv_rel, parquet_rel in DATASETS.items():
        csv_path = REPO_ROOT / "datasets" / csv_rel
        parquet_path = REPO_ROOT / "datasets" / parquet_rel
        if not csv_path.is_file():
            print(f"SKIP: source CSV missing: {csv_path}")
            continue
        frame = pl.read_csv(csv_path)
        frame.write_parquet(parquet_path)
        print(f"WROTE: {parquet_path.relative_to(REPO_ROOT)} ({len(frame)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
