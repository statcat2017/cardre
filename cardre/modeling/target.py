"""Target specification — canonical target encoding and validation.

Centralises the duplicated target-column cast/validate/encode logic
that was previously inline in 5+ node files.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class TargetSpec:
    target_column: str
    good_values: frozenset[str]
    bad_values: frozenset[str]
    indeterminate_values: frozenset[str] = frozenset()
    all_known: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.all_known:
            object.__setattr__(self, "all_known", self.good_values | self.bad_values | self.indeterminate_values)

    @classmethod
    def from_metadata(cls, meta: object) -> TargetSpec:
        """Build a strict TargetSpec from a typing-metadata object.

        Requires the current metadata type and fields; missing or mis-shaped
        fields are an error rather than a legacy-null fallback. ``all_known``
        is always derived from good/bad/indeterminate — it is never read off
        the metadata.
        """
        if meta is None:
            raise ValueError("Target metadata is required; received None")
        target_column = getattr(meta, "target_column", "")
        if not isinstance(target_column, str) or not target_column:
            raise ValueError("Target metadata requires a non-empty target_column")
        good = getattr(meta, "good_values", None)
        bad = getattr(meta, "bad_values", None)
        indet = getattr(meta, "indeterminate_values", None)
        if good is None or bad is None:
            raise ValueError("Target metadata requires good_values and bad_values")
        good_set = frozenset(str(v) for v in good)
        bad_set = frozenset(str(v) for v in bad)
        if not good_set or not bad_set:
            raise ValueError("Target metadata requires non-empty good_values and bad_values")
        indet_set = frozenset(str(v) for v in indet) if indet is not None else frozenset()
        return cls(
            target_column=target_column,
            good_values=good_set,
            bad_values=bad_set,
            indeterminate_values=indet_set,
            all_known=good_set | bad_set | indet_set,
        )

    def validate_known(self, df: pl.DataFrame) -> None:
        if self.target_column not in df.columns:
            raise ValueError(f"Target column '{self.target_column}' not found in data")
        raw = df[self.target_column].cast(pl.String)
        known = raw.is_in(list(self.all_known)) if self.all_known else pl.Series([True] * df.height)
        unknown = raw.filter(~known).unique().to_list()
        if unknown:
            raise ValueError(
                f"Target column '{self.target_column}' contains {len(unknown)} value(s) "
                f"not declared as good, bad, or indeterminate: {sorted(unknown)[:10]}."
            )

    def validate_good_bad_only(self, df: pl.DataFrame) -> None:
        """Reject any row whose target value is not in good_values or bad_values.

        Indeterminate values are treated as unknown and raise an error.
        This is the strict policy used by model training, logistic regression,
        and WOE/IV calculation.
        """
        if self.target_column not in df.columns:
            raise ValueError(f"Target column '{self.target_column}' not found in data")
        raw = df[self.target_column].cast(pl.String)
        known = raw.is_in(list(self.good_values | self.bad_values))
        unknown = raw.filter(~known).unique().to_list()
        if unknown:
            raise ValueError(
                f"Target column '{self.target_column}' contains {len(unknown)} value(s) "
                f"not declared as good or bad: {sorted(unknown)[:10]}. "
                f"Every row must be explicitly classified."
            )

    def encode_binary(self, df: pl.DataFrame) -> pl.Series:
        """Encode target as binary (bad=1, everything else=0).

        Validates that all values are in all_known (good, bad, or indeterminate).
        Indeterminate values are encoded as 0 (non-bad).
        """
        self.validate_known(df)
        return df[self.target_column].cast(pl.String).is_in(list(self.bad_values)).cast(pl.Int64)

    def encode_binary_strict(self, df: pl.DataFrame) -> pl.Series:
        """Encode target as binary (bad=1, good=0), rejecting indeterminate values.

        This is the strict policy used by model training, logistic regression,
        and WOE/IV calculation. Every row must be explicitly good or bad.
        """
        self.validate_good_bad_only(df)
        return df[self.target_column].cast(pl.String).is_in(list(self.bad_values)).cast(pl.Int64)

    def counts(self, df: pl.DataFrame) -> tuple[int, int, int]:
        target_str = df[self.target_column].cast(pl.String)
        n_good = int(target_str.is_in(list(self.good_values)).sum())
        n_bad = int(target_str.is_in(list(self.bad_values)).sum())
        return n_good, n_bad, df.height

    def bad_mask_expr(self) -> pl.Expr:
        return pl.col(self.target_column).cast(pl.String).is_in(list(self.bad_values))

    def good_mask_expr(self) -> pl.Expr:
        return pl.col(self.target_column).cast(pl.String).is_in(list(self.good_values))
