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

    @classmethod
    def from_metadata(cls, meta: object) -> TargetSpec | None:
        if meta is None:
            return None
        target_column = getattr(meta, "target_column", "")
        if not target_column:
            return None
        good = frozenset(str(v) for v in getattr(meta, "good_values", []))
        bad = frozenset(str(v) for v in getattr(meta, "bad_values", []))
        indet = frozenset(str(v) for v in getattr(meta, "indeterminate_values", []))
        all_known = frozenset(str(v) for v in getattr(meta, "all_known", [])) if hasattr(meta, "all_known") else good | bad | indet
        return cls(
            target_column=target_column,
            good_values=good,
            bad_values=bad,
            indeterminate_values=indet,
            all_known=all_known,
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

    def encode_binary(self, df: pl.DataFrame) -> pl.Series:
        self.validate_known(df)
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
