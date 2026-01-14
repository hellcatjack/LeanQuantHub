from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


PIT_META_FIELDS = {
    "symbol",
    "snapshot_date",
    "rebalance_date",
    "fiscal_date",
    "reported_date",
    "available_date",
}

PIT_FEATURE_FIELDS = [
    "has_fundamentals",
    "lag_days",
    "total_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps",
    "reported_eps",
    "total_assets",
    "total_liabilities",
    "total_shareholder_equity",
    "cash_and_cash_equivalents",
    "operating_cashflow",
    "capital_expenditures",
    "cashflow_from_investment",
    "cashflow_from_financing",
    "free_cashflow",
]

PIT_RENAME = {field: f"pit_{field}" for field in PIT_FEATURE_FIELDS}
PIT_FEATURE_COLUMNS = list(PIT_RENAME.values())
PIT_EXTRA_FIELDS = ["pit_market_cap"]
PIT_ALL_COLUMNS = PIT_FEATURE_COLUMNS + PIT_EXTRA_FIELDS
PIT_MISSING_RATIO_FIELD = "pit_missing_ratio"


def _parse_date(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()


def _read_snapshot(path: Path) -> pd.DataFrame:
    usecols = ["symbol", "snapshot_date", *PIT_FEATURE_FIELDS, *PIT_EXTRA_FIELDS]
    try:
        df = pd.read_csv(path, usecols=usecols)
    except ValueError:
        df = pd.read_csv(path)
        keep = [col for col in usecols if col in df.columns]
        df = df[keep]
    return df


def _coerce_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def load_pit_fundamentals(
    pit_dir: Path,
    symbols: Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    min_coverage: float = 0.0,
    coverage_action: str = "warn",
) -> tuple[dict[str, pd.DataFrame], list[str], dict[str, float]]:
    if not pit_dir.exists():
        raise RuntimeError(f"missing pit fundamentals dir: {pit_dir}")
    symbol_set = {str(symbol).strip().upper() for symbol in symbols or [] if str(symbol).strip()}
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)

    pit_frames: dict[str, list[pd.DataFrame]] = {}
    total_rows = 0
    total_with_data = 0

    for path in sorted(pit_dir.glob("pit_fundamentals_*.csv")):
        snapshot = _read_snapshot(path)
        if snapshot.empty:
            continue
        snapshot["symbol"] = snapshot["symbol"].astype(str).str.upper()
        snapshot["snapshot_date"] = pd.to_datetime(snapshot["snapshot_date"], errors="coerce")
        snapshot = snapshot.dropna(subset=["symbol", "snapshot_date"])
        if symbol_set:
            snapshot = snapshot[snapshot["symbol"].isin(symbol_set)]
        if start_dt is not None:
            snapshot = snapshot[snapshot["snapshot_date"] >= start_dt]
        if end_dt is not None:
            snapshot = snapshot[snapshot["snapshot_date"] <= end_dt]
        if snapshot.empty:
            continue

        total_rows += len(snapshot)
        if "has_fundamentals" in snapshot.columns:
            total_with_data += int(
                pd.to_numeric(snapshot["has_fundamentals"], errors="coerce")
                .fillna(0.0)
                .gt(0)
                .sum()
            )

        snapshot = _coerce_numeric(snapshot, [*PIT_FEATURE_FIELDS, *PIT_EXTRA_FIELDS])
        snapshot = snapshot.rename(columns=PIT_RENAME)
        for col in PIT_FEATURE_COLUMNS:
            if col not in snapshot.columns:
                snapshot[col] = np.nan
        for col in PIT_EXTRA_FIELDS:
            if col not in snapshot.columns:
                snapshot[col] = np.nan

        for symbol, group in snapshot.groupby("symbol"):
            frame = group.drop(columns=["symbol"]).set_index("snapshot_date").sort_index()
            frame = frame[PIT_ALL_COLUMNS]
            pit_frames.setdefault(symbol, []).append(frame)

    result: dict[str, pd.DataFrame] = {}
    for symbol, frames in pit_frames.items():
        combined = pd.concat(frames).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        result[symbol] = combined

    coverage = (total_with_data / total_rows) if total_rows else 0.0
    min_coverage = max(min(float(min_coverage), 1.0), 0.0)
    action = str(coverage_action or "warn").strip().lower()
    if total_rows and coverage < min_coverage:
        message = f"pit coverage below threshold ratio={coverage:.4f} min={min_coverage:.4f}"
        if action == "fail":
            raise RuntimeError(message)
        if action == "warn":
            print(f"warning: {message}")
        else:
            raise RuntimeError("pit coverage_action must be warn or fail")

    summary = {
        "total_rows": float(total_rows),
        "with_data": float(total_with_data),
        "coverage": float(coverage),
    }
    return result, PIT_ALL_COLUMNS, summary


def apply_pit_features(
    features: pd.DataFrame,
    pit_frame: pd.DataFrame | None,
    pit_fields: Iterable[str],
    sample_on_snapshot: bool,
    missing_policy: str,
) -> pd.DataFrame:
    pit_fields = list(pit_fields)
    policy = str(missing_policy or "fill_zero").strip().lower()
    if pit_frame is None or pit_frame.empty:
        if sample_on_snapshot:
            return features.iloc[0:0]
        if pit_fields:
            for col in pit_fields:
                features[col] = 0.0
            if "pit_has_fundamentals" in features.columns:
                features["pit_has_fundamentals"] = 0.0
            features[PIT_MISSING_RATIO_FIELD] = 1.0
        if policy == "drop":
            return features.iloc[0:0]
        return features
    if sample_on_snapshot:
        features = features.loc[features.index.isin(pit_frame.index)]
        if features.empty:
            return features
        merged = features.join(pit_frame, how="left")
    else:
        features = features.sort_index()
        pit_frame = pit_frame.sort_index()
        merged = pd.merge_asof(
            features,
            pit_frame,
            left_index=True,
            right_index=True,
            direction="backward",
            allow_exact_matches=True,
        )
    if merged.empty:
        return merged
    if policy == "drop" and "pit_has_fundamentals" in merged.columns:
        merged = merged[merged["pit_has_fundamentals"].fillna(0) > 0]
    missing_fields = [col for col in pit_fields if col != "pit_has_fundamentals"]
    if missing_fields:
        merged[PIT_MISSING_RATIO_FIELD] = merged[missing_fields].isna().mean(axis=1)
        merged[missing_fields] = merged[missing_fields].fillna(0.0)
    if "pit_has_fundamentals" in merged.columns:
        merged["pit_has_fundamentals"] = merged["pit_has_fundamentals"].fillna(0.0)
    return merged
