"""Dataset-quality warning helpers for ProfileDatasetNode.

Scans a Polars DataFrame for common dataset-quality issues such as
suspect column names (ID, date, leakage), constant/near-unique/dominant
columns, high-cardinality categoricals, null-heavy columns, string-coded
numerics, date-like strings, duplicate rows, and blank/duplicate column names.

All checks return warning dicts—no automatic exclusion.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from cardre.domain.diagnostics import JsonDict

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

NEAR_UNIQUE_RATIO: float = 0.95
DOMINANT_VALUE_RATIO: float = 0.95
HIGH_CARDINALITY_CUTOFF: int = 50
HIGH_CARDINALITY_UNIQUE_RATIO: float = 0.5
NULL_HEAVY_RATIO: float = 0.5
STRING_NUMERIC_THRESHOLD: float = 0.9
DATE_LIKE_THRESHOLD: float = 0.8
MIN_ROWS_FOR_NEAR_UNIQUE: int = 20

# ---------------------------------------------------------------------------
# Column-name patterns
# ---------------------------------------------------------------------------

_ID_PATTERNS: tuple[str, ...] = (
    "id", "_id", "customer_id", "application_id", "loan_id",
    "account_id", "uuid", "user_id", "client_id", "policy_id",
)
_DATE_PATTERNS: tuple[str, ...] = (
    "date", "_dt", "timestamp", "time",
    "opened_at", "closed_at", "created_at", "updated_at",
    "application_date", "decision_date",
)
_LEAKAGE_PATTERNS: tuple[str, ...] = (
    "default", "bad", "chargeoff", "writeoff", "delinq", "dpd",
    "arrears", "collection", "recovery", "loss", "outcome",
    "performance", "post_",
)

_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def quality_warnings(df: pl.DataFrame) -> tuple[list[JsonDict], list[str]]:
    """Scan *df* for dataset-quality issues.

    Returns ``(warnings, recommended_exclude_columns)``.
    """
    warnings: list[JsonDict] = []
    recommended: set[str] = set()

    if df.height == 0:
        return warnings, []

    _check_duplicate_rows(df, warnings)
    _check_column_names(df, warnings, recommended)

    for col in df.columns:
        series = df[col]
        _check_suspect_name(col, warnings, recommended)
        _check_constant(col, series, warnings, recommended)
        _check_near_unique(col, series, warnings, recommended)
        _check_dominant_value(col, series, warnings, recommended)
        _check_high_cardinality(col, series, warnings, recommended)
        _check_null_heavy(col, series, warnings, recommended)
        _check_string_coded_numeric(col, series, warnings, recommended)
        _check_date_like_string(col, series, warnings, recommended)

    return warnings, sorted(recommended)


# ---------------------------------------------------------------------------
# Warning factory
# ---------------------------------------------------------------------------


def _warning(code: str, column: str, message: str, *,
             severity: str = "warning",
             recommended_action: str = "review") -> JsonDict:
    return {
        "code": code,
        "severity": severity,
        "column": column,
        "message": message,
        "recommended_action": recommended_action,
    }


# ---------------------------------------------------------------------------
# Dataset-level checks
# ---------------------------------------------------------------------------


def _check_duplicate_rows(df: pl.DataFrame, warnings: list[JsonDict]) -> None:
    dup_count = df.height - df.unique().height
    if dup_count > 0:
        warnings.append(_warning(
            "DUPLICATE_ROWS", "",
            f"Dataset contains {dup_count} duplicate row(s).",
            severity="warning", recommended_action="review",
        ))


def _check_column_names(df: pl.DataFrame, warnings: list[JsonDict],
                        recommended: set[str]) -> None:
    for col in df.columns:
        if not col or col.strip() == "":
            warnings.append(_warning(
                "BLANK_COLUMN_NAME", col,
                f"Column {col!r} has a blank or whitespace-only name.",
                severity="warning", recommended_action="rename",
            ))
        if "duplicated" in col.lower():
            warnings.append(_warning(
                "DUPLICATE_IMPORTED_COLUMN_NAME", col,
                f"Column {col!r} appears to be a Polars-renamed duplicate. "
                f"The original import had duplicate column names.",
                severity="warning", recommended_action="rename",
            ))


# ---------------------------------------------------------------------------
# Per-column checks
# ---------------------------------------------------------------------------


def _check_suspect_name(col: str, warnings: list[JsonDict],
                        recommended: set[str]) -> None:
    col_lower = col.lower()
    for pat in _ID_PATTERNS:
        if col_lower == pat or col_lower.endswith("_" + pat) or col_lower.startswith(pat + "_"):
            warnings.append(_warning(
                "SUSPECT_ID_COLUMN", col,
                f"Column {col!r} looks like an identifier and should usually be excluded "
                f"from modelling.",
                severity="warning", recommended_action="exclude",
            ))
            recommended.add(col)
            return
    for pat in _DATE_PATTERNS:
        if pat in col_lower:
            warnings.append(_warning(
                "SUSPECT_DATE_COLUMN", col,
                f"Column {col!r} looks like a date/timestamp and may need special handling.",
                severity="info", recommended_action="review",
            ))
            recommended.add(col)
            return
    for pat in _LEAKAGE_PATTERNS:
        if pat in col_lower:
            warnings.append(_warning(
                "SUSPECT_LEAKAGE_COLUMN", col,
                f"Column {col!r} looks like it may contain post-outcome or leakage "
                f"information. Verify this column is not target-derived.",
                severity="warning", recommended_action="review",
            ))
            recommended.add(col)
            return


def _check_constant(col: str, series: pl.Series, warnings: list[JsonDict],
                    recommended: set[str]) -> None:
    non_null = series.drop_nulls()
    if non_null.len() > 0 and non_null.n_unique() <= 1:
        warnings.append(_warning(
            "CONSTANT_COLUMN", col,
            f"Column {col!r} has only one unique non-null value.",
            severity="warning", recommended_action="exclude",
        ))
        recommended.add(col)


def _check_near_unique(col: str, series: pl.Series, warnings: list[JsonDict],
                       recommended: set[str]) -> None:
    non_null = series.drop_nulls()
    n = non_null.len()
    if n >= MIN_ROWS_FOR_NEAR_UNIQUE:
        u = non_null.n_unique()
        if u / n >= NEAR_UNIQUE_RATIO:
            warnings.append(_warning(
                "NEAR_UNIQUE_COLUMN", col,
                f"Column {col!r} has {u} unique values out of {n} rows "
                f"({u/n:.1%}). Near-unique columns are usually identifiers.",
                severity="warning", recommended_action="exclude",
            ))
            recommended.add(col)


def _check_dominant_value(col: str, series: pl.Series,
                          warnings: list[JsonDict], recommended: set[str]) -> None:
    if series.dtype.is_numeric():
        non_null = series.drop_nulls()
        if non_null.len() == 0:
            return
        vc = non_null.value_counts().sort("count", descending=True)
        top_share = vc["count"][0] / non_null.len()
        if top_share >= DOMINANT_VALUE_RATIO:
            warnings.append(_warning(
                "DOMINANT_VALUE_COLUMN", col,
                f"Column {col!r} has a single value in {top_share:.1%} of rows.",
                severity="info", recommended_action="review",
            ))


def _check_high_cardinality(col: str, series: pl.Series,
                            warnings: list[JsonDict], recommended: set[str]) -> None:
    if not series.dtype.is_numeric():
        non_null = series.drop_nulls()
        n = non_null.len()
        if n == 0:
            return
        u = non_null.n_unique()
        if u > HIGH_CARDINALITY_CUTOFF or u / n >= HIGH_CARDINALITY_UNIQUE_RATIO:
            warnings.append(_warning(
                "HIGH_CARDINALITY_CATEGORICAL", col,
                f"Column {col!r} has {u} unique values ({u/n:.1%} of rows). "
                f"High-cardinality categoricals may need special binning.",
                severity="info", recommended_action="review",
            ))


def _check_null_heavy(col: str, series: pl.Series,
                      warnings: list[JsonDict], recommended: set[str]) -> None:
    if series.null_count() / max(series.len(), 1) >= NULL_HEAVY_RATIO:
        warnings.append(_warning(
            "NULL_HEAVY_COLUMN", col,
            f"Column {col!r} has {series.null_count()} null values out of "
            f"{series.len()} rows ({series.null_count()/series.len():.1%}).",
            severity="warning", recommended_action="review",
        ))


def _check_string_coded_numeric(col: str, series: pl.Series,
                                 warnings: list[JsonDict], recommended: set[str]) -> None:
    if series.dtype == pl.Utf8:
        non_null = series.drop_nulls()
        n = non_null.len()
        if n < 2:
            return
        cleaned = non_null.str.replace(",", "").str.replace(r"^\s*\$", "")
        numeric_count = 0
        for val in cleaned:
            try:
                float(val)
                numeric_count += 1
            except (ValueError, TypeError):
                pass
        if numeric_count / n >= STRING_NUMERIC_THRESHOLD:
            warnings.append(_warning(
                "STRING_CODED_NUMERIC", col,
                f"Column {col!r} is stored as string but {numeric_count}/{n} "
                f"({numeric_count/n:.0%}) non-null values parse as numeric. "
                f"Consider importing with a schema override.",
                severity="warning", recommended_action="review",
            ))


def _check_date_like_string(col: str, series: pl.Series,
                             warnings: list[JsonDict], recommended: set[str]) -> None:
    if series.dtype == pl.Utf8:
        non_null = series.drop_nulls()
        n = non_null.len()
        if n < 2:
            return
        date_count = 0
        for val in non_null:
            for fmt in _DATE_FORMATS:
                try:
                    datetime.strptime(str(val)[:19], fmt)
                    date_count += 1
                    break
                except (ValueError, TypeError):
                    pass
        if date_count / n >= DATE_LIKE_THRESHOLD:
            warnings.append(_warning(
                "DATE_LIKE_STRING", col,
                f"Column {col!r} is stored as string but {date_count}/{n} "
                f"({date_count/n:.0%}) non-null values parse as dates. "
                f"Consider importing with a date schema override.",
                severity="info", recommended_action="review",
            ))
