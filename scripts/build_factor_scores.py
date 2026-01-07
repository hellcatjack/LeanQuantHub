#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class FactorConfig:
    momentum_windows: list[int]
    vol_window: int
    liquidity_window: int
    winsor_z: float
    weights: dict[str, float]


def _resolve_data_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    default_root = Path("/data/share/stock/data")
    if default_root.exists():
        return default_root
    return Path.cwd() / "data"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    if not text or text.lower() in {"null", "none", "na", "n/a"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _load_symbol_map(
    path: Path,
) -> dict[str, list[tuple[date | None, date | None, str]]]:
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]] = {}
    if not path.exists():
        return symbol_map
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            canonical = (row.get("canonical") or "").strip().upper()
            if not symbol or not canonical:
                continue
            start = _parse_date(row.get("start_date") or row.get("from_date") or "")
            end = _parse_date(row.get("end_date") or row.get("to_date") or "")
            symbol_map.setdefault(symbol, []).append((start, end, canonical))
    for entries in symbol_map.values():
        entries.sort(key=lambda item: item[0] or date.min)
    return symbol_map


def _resolve_symbol_alias(
    symbol: str,
    as_of: date | None,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
) -> str:
    entries = symbol_map.get(symbol)
    if not entries:
        return symbol
    if as_of:
        match = None
        for start, end, canonical in entries:
            if start and as_of < start:
                continue
            if end and as_of > end:
                continue
            match = canonical
        if match:
            return match
    return entries[-1][2]


def _extract_symbol_from_filename(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_", 2)
    if len(parts) >= 3:
        symbol_part = parts[2]
    else:
        symbol_part = stem
    for suffix in ("_Daily", "_daily", "_D", "_d"):
        if symbol_part.endswith(suffix):
            symbol_part = symbol_part[: -len(suffix)]
            break
    return symbol_part.strip().upper()


def _load_exclude_symbols(paths: Iterable[Path]) -> set[str]:
    symbols: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
    return symbols


def _load_snapshot_index(
    pit_weekly_dir: Path,
    start: date | None,
    end: date | None,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
    exclude_symbols: set[str],
) -> tuple[dict[date, set[str]], dict[str, list[date]], list[date]]:
    snapshot_symbols: dict[date, set[str]] = {}
    symbol_dates: dict[str, list[date]] = defaultdict(list)

    for path in sorted(pit_weekly_dir.glob("pit_*.csv")):
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                symbol_raw = (row.get("symbol") or "").strip().upper()
                snapshot_raw = (row.get("snapshot_date") or "").strip()
                if not symbol_raw or not snapshot_raw:
                    continue
                snapshot_date = _parse_date(snapshot_raw)
                if snapshot_date is None:
                    continue
                if start and snapshot_date < start:
                    continue
                if end and snapshot_date > end:
                    continue
                symbol = _resolve_symbol_alias(symbol_raw, snapshot_date, symbol_map)
                if symbol in exclude_symbols:
                    continue
                snapshot_symbols.setdefault(snapshot_date, set()).add(symbol)
                symbol_dates[symbol].append(snapshot_date)

    for symbol, dates in symbol_dates.items():
        symbol_dates[symbol] = sorted(set(dates))
    snapshot_dates = sorted(snapshot_symbols.keys())
    return snapshot_symbols, symbol_dates, snapshot_dates


def _pick_price_file(adjusted_dir: Path, symbol: str) -> Path | None:
    variants = [symbol]
    if "." in symbol:
        variants.append(symbol.replace(".", "_"))
    if "-" in symbol:
        variants.append(symbol.replace("-", "_"))
    candidates: list[Path] = []
    for variant in variants:
        candidates.extend(adjusted_dir.glob(f"*_{variant}_*.csv"))
        candidates.extend(adjusted_dir.glob(f"*_{variant}.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_size)


def _load_price_metrics(path: Path, config: FactorConfig) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=["date", "close", "volume"])
    df.columns = [col.strip().lower() for col in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df = df.set_index("date")

    for window in config.momentum_windows:
        df[f"ret_{window}"] = df["close"].pct_change(window)
    df["vol"] = df["close"].pct_change().rolling(config.vol_window).std()
    df["adv"] = (df["close"] * df["volume"]).rolling(config.liquidity_window).mean()
    return df


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = denominator.replace(0, np.nan)
    return numerator / denom


def _zscore(series: pd.Series, winsor_z: float) -> pd.Series:
    series = series.astype(float)
    mean = series.mean(skipna=True)
    std = series.std(skipna=True)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=series.index)
    z = (series - mean) / std
    if winsor_z > 0:
        z = z.clip(lower=-winsor_z, upper=winsor_z)
    return z


class RawWriter:
    def __init__(self, cache_dir: Path, fieldnames: list[str], max_open: int = 64) -> None:
        self.cache_dir = cache_dir
        self.fieldnames = fieldnames
        self.max_open = max_open
        self._handles: OrderedDict[str, tuple[Path, csv.DictWriter, object]] = OrderedDict()

    def write(self, date_key: str, row: dict[str, object]) -> None:
        if date_key in self._handles:
            path, writer, handle = self._handles.pop(date_key)
            self._handles[date_key] = (path, writer, handle)
            writer.writerow(row)
            return
        path = self.cache_dir / f"raw_{date_key}.csv"
        exists = path.exists()
        handle = path.open("a", encoding="utf-8", newline="")
        writer = csv.DictWriter(handle, fieldnames=self.fieldnames)
        if not exists or path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)
        self._handles[date_key] = (path, writer, handle)
        if len(self._handles) > self.max_open:
            _, (_, _, old_handle) = self._handles.popitem(last=False)
            old_handle.close()

    def close(self) -> None:
        for _, (_, _, handle) in self._handles.items():
            handle.close()
        self._handles.clear()


def _load_fundamentals_snapshot(
    pit_dir: Path,
    snapshot_date: date,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
    exclude_symbols: set[str],
) -> pd.DataFrame:
    filename = f"pit_fundamentals_{snapshot_date.strftime('%Y%m%d')}.csv"
    path = pit_dir / filename
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df.columns = [col.strip() for col in df.columns]
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["symbol"] = df["symbol"].apply(lambda sym: _resolve_symbol_alias(sym, snapshot_date, symbol_map))
    if exclude_symbols:
        df = df[~df["symbol"].isin(exclude_symbols)]
    return df


def _load_factor_config(path: Path | None) -> FactorConfig:
    if path and path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = {}
    momentum_windows = raw.get("momentum_windows") or [63, 126, 252]
    vol_window = int(raw.get("vol_window") or 60)
    liquidity_window = int(raw.get("liquidity_window") or 20)
    winsor_z = float(raw.get("winsor_z") or 3.0)
    weights = raw.get("weights") or {
        "momentum": 0.2,
        "quality": 0.2,
        "value": 0.2,
        "low_vol": 0.2,
        "liquidity": 0.2,
    }
    return FactorConfig(
        momentum_windows=list(momentum_windows),
        vol_window=vol_window,
        liquidity_window=liquidity_window,
        winsor_z=winsor_z,
        weights={str(key): float(value) for key, value in weights.items()},
    )


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(value, 0.0) for value in weights.values())
    if total <= 0:
        return {key: 0.0 for key in weights}
    return {key: max(value, 0.0) / total for key, value in weights.items()}


def build_scores(
    snapshot_symbols: dict[date, set[str]],
    symbol_dates: dict[str, list[date]],
    snapshot_dates: list[date],
    adjusted_dir: Path,
    pit_fundamentals_dir: Path,
    symbol_map: dict[str, list[tuple[date | None, date | None, str]]],
    exclude_symbols: set[str],
    config: FactorConfig,
    cache_dir: Path,
    output_path: Path,
    overwrite_cache: bool,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if overwrite_cache:
        for path in cache_dir.glob("raw_*.csv"):
            path.unlink()

    momentum_fields = [f"ret_{window}" for window in config.momentum_windows]
    raw_fields = ["symbol", "date", "price", *momentum_fields, "vol", "adv"]

    writer = RawWriter(cache_dir, raw_fields)
    missing_prices: list[str] = []

    for idx, (symbol, dates) in enumerate(symbol_dates.items(), start=1):
        price_path = _pick_price_file(adjusted_dir, symbol)
        if price_path is None:
            missing_prices.append(symbol)
            continue
        price_df = _load_price_metrics(price_path, config)
        if price_df.empty:
            missing_prices.append(symbol)
            continue
        date_index = pd.to_datetime(dates)
        slice_df = price_df.reindex(date_index, method="pad")
        slice_df = slice_df[["close", *momentum_fields, "vol", "adv"]]
        for ts, row in slice_df.iterrows():
            if pd.isna(ts):
                continue
            date_key = ts.date().strftime("%Y%m%d")
            row_values = {field: row.get(field, np.nan) for field in momentum_fields}
            writer.write(
                date_key,
                {
                    "symbol": symbol,
                    "date": ts.date().isoformat(),
                    "price": row.get("close", np.nan),
                    **row_values,
                    "vol": row.get("vol", np.nan),
                    "adv": row.get("adv", np.nan),
                },
            )
        if idx % 500 == 0:
            print(f"progress: {idx} / {len(symbol_dates)} symbols")
    writer.close()

    quality_fields = [
        "gross_margin",
        "operating_margin",
        "net_margin",
        "roe",
        "roa",
        "fcf_margin",
    ]

    weight_map = _normalize_weights(config.weights)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "date",
                "symbol",
                "score",
                "score_momentum",
                "score_quality",
                "score_value",
                "score_low_vol",
                "score_liquidity",
            ],
        )
        writer.writeheader()

        for snapshot_date in snapshot_dates:
            date_key = snapshot_date.strftime("%Y%m%d")
            raw_path = cache_dir / f"raw_{date_key}.csv"
            if not raw_path.exists():
                continue
            raw_df = pd.read_csv(raw_path)
            if raw_df.empty:
                continue
            raw_df["symbol"] = raw_df["symbol"].astype(str).str.upper()
            raw_df = raw_df[raw_df["symbol"].isin(snapshot_symbols.get(snapshot_date, set()))]
            if raw_df.empty:
                continue

            fundamentals = _load_fundamentals_snapshot(
                pit_fundamentals_dir, snapshot_date, symbol_map, exclude_symbols
            )
            if not fundamentals.empty:
                fundamentals = fundamentals.drop_duplicates(subset=["symbol"], keep="last")
            merged = raw_df.merge(fundamentals, on="symbol", how="left")
            for col in [
                "gross_profit",
                "operating_income",
                "net_income",
                "total_revenue",
                "total_shareholder_equity",
                "total_assets",
                "free_cashflow",
                "eps",
                "reported_eps",
            ]:
                if col not in merged.columns:
                    merged[col] = np.nan
            merged["eps_used"] = merged["eps"]
            eps_missing = merged["eps_used"].isna()
            if "reported_eps" in merged.columns:
                merged.loc[eps_missing, "eps_used"] = merged.loc[eps_missing, "reported_eps"]

            merged["gross_margin"] = _safe_div(merged["gross_profit"], merged["total_revenue"])
            merged["operating_margin"] = _safe_div(merged["operating_income"], merged["total_revenue"])
            merged["net_margin"] = _safe_div(merged["net_income"], merged["total_revenue"])
            merged["roe"] = _safe_div(merged["net_income"], merged["total_shareholder_equity"])
            merged["roa"] = _safe_div(merged["net_income"], merged["total_assets"])
            merged["fcf_margin"] = _safe_div(merged["free_cashflow"], merged["total_revenue"])
            merged["earnings_yield"] = _safe_div(merged["eps_used"], merged["price"])
            merged["low_vol"] = -merged["vol"]
            merged["liquidity"] = np.log1p(merged["adv"].clip(lower=0))

            momentum_z_cols = []
            for window in config.momentum_windows:
                col = f"ret_{window}"
                z_col = f"z_ret_{window}"
                merged[z_col] = _zscore(merged[col], config.winsor_z)
                momentum_z_cols.append(z_col)
            merged["z_low_vol"] = _zscore(merged["low_vol"], config.winsor_z)
            merged["z_liquidity"] = _zscore(merged["liquidity"], config.winsor_z)
            merged["z_earnings_yield"] = _zscore(merged["earnings_yield"], config.winsor_z)

            for field in quality_fields:
                merged[f"z_{field}"] = _zscore(merged[field], config.winsor_z)

            merged["score_momentum"] = merged[momentum_z_cols].mean(axis=1, skipna=True)
            merged["score_quality"] = merged[[f"z_{field}" for field in quality_fields]].mean(
                axis=1, skipna=True
            )
            merged["score_value"] = merged["z_earnings_yield"]
            merged["score_low_vol"] = merged["z_low_vol"]
            merged["score_liquidity"] = merged["z_liquidity"]

            for col in [
                "score_momentum",
                "score_quality",
                "score_value",
                "score_low_vol",
                "score_liquidity",
            ]:
                merged[col] = merged[col].fillna(0.0)

            merged["score"] = (
                weight_map.get("momentum", 0.0) * merged["score_momentum"]
                + weight_map.get("quality", 0.0) * merged["score_quality"]
                + weight_map.get("value", 0.0) * merged["score_value"]
                + weight_map.get("low_vol", 0.0) * merged["score_low_vol"]
                + weight_map.get("liquidity", 0.0) * merged["score_liquidity"]
            )

            for _, row in merged.iterrows():
                writer.writerow(
                    {
                        "date": snapshot_date.isoformat(),
                        "symbol": row["symbol"],
                        "score": f"{row['score']:.8f}",
                        "score_momentum": f"{row['score_momentum']:.8f}",
                        "score_quality": f"{row['score_quality']:.8f}",
                        "score_value": f"{row['score_value']:.8f}",
                        "score_low_vol": f"{row['score_low_vol']:.8f}",
                        "score_liquidity": f"{row['score_liquidity']:.8f}",
                    }
                )

    if missing_prices:
        print(f"missing price data: {len(missing_prices)} symbols")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=str, default="")
    parser.add_argument(
        "--pit-weekly-dir",
        type=str,
        default="",
        help="PIT 周度快照目录（默认 data_root/universe/pit_weekly）",
    )
    parser.add_argument(
        "--pit-fundamentals-dir",
        type=str,
        default="",
        help="PIT 基本面快照目录（默认 data_root/factors/pit_weekly_fundamentals）",
    )
    parser.add_argument(
        "--adjusted-dir",
        type=str,
        default="",
        help="复权行情目录（默认 data_root/curated_adjusted）",
    )
    parser.add_argument(
        "--symbol-map",
        type=str,
        default="",
        help="symbol_map.csv 路径（默认 data_root/universe/symbol_map.csv）",
    )
    parser.add_argument(
        "--exclude-symbols",
        type=str,
        default="",
        help="排除标的 CSV，支持逗号分隔多个路径",
    )
    parser.add_argument("--start", type=str, default="")
    parser.add_argument("--end", type=str, default="")
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="因子权重配置（默认 configs/factor_scores.json）",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="",
        help="临时缓存目录（默认 artifacts/factor_cache）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="输出 scores.csv（默认 ml/models/factor_scores.csv）",
    )
    parser.add_argument(
        "--overwrite-cache",
        action="store_true",
        help="清空缓存目录后重新生成",
    )
    args = parser.parse_args()

    data_root = _resolve_data_root(args.data_root)
    pit_weekly_dir = (
        Path(args.pit_weekly_dir).expanduser().resolve()
        if args.pit_weekly_dir
        else data_root / "universe" / "pit_weekly"
    )
    pit_fundamentals_dir = (
        Path(args.pit_fundamentals_dir).expanduser().resolve()
        if args.pit_fundamentals_dir
        else data_root / "factors" / "pit_weekly_fundamentals"
    )
    adjusted_dir = (
        Path(args.adjusted_dir).expanduser().resolve()
        if args.adjusted_dir
        else data_root / "curated_adjusted"
    )
    symbol_map_path = (
        Path(args.symbol_map).expanduser().resolve()
        if args.symbol_map
        else data_root / "universe" / "symbol_map.csv"
    )
    config_path = (
        Path(args.config).expanduser().resolve()
        if args.config
        else Path(__file__).resolve().parents[1] / "configs" / "factor_scores.json"
    )
    cache_dir = (
        Path(args.cache_dir).expanduser().resolve()
        if args.cache_dir
        else Path(__file__).resolve().parents[1] / "artifacts" / "factor_cache"
    )
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else Path(__file__).resolve().parents[1] / "ml" / "models" / "factor_scores.csv"
    )

    if not pit_weekly_dir.exists():
        raise SystemExit(f"missing pit_weekly_dir: {pit_weekly_dir}")
    if not pit_fundamentals_dir.exists():
        raise SystemExit(f"missing pit_fundamentals_dir: {pit_fundamentals_dir}")
    if not adjusted_dir.exists():
        raise SystemExit(f"missing adjusted_dir: {adjusted_dir}")

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    symbol_map = _load_symbol_map(symbol_map_path) if symbol_map_path.exists() else {}

    exclude_paths = []
    if args.exclude_symbols:
        for raw in args.exclude_symbols.split(","):
            raw = raw.strip()
            if raw:
                exclude_paths.append(Path(raw).expanduser().resolve())
    else:
        defaults = [
            data_root / "universe" / "fundamentals_exclude.csv",
            data_root / "universe" / "exclude_symbols.csv",
        ]
        exclude_paths = [path for path in defaults if path.exists()]
    exclude_symbols = _load_exclude_symbols(exclude_paths)

    config = _load_factor_config(config_path if config_path.exists() else None)

    snapshot_symbols, symbol_dates, snapshot_dates = _load_snapshot_index(
        pit_weekly_dir, start, end, symbol_map, exclude_symbols
    )
    if not snapshot_dates:
        raise SystemExit("no pit snapshots found in range")

    build_scores(
        snapshot_symbols,
        symbol_dates,
        snapshot_dates,
        adjusted_dir,
        pit_fundamentals_dir,
        symbol_map,
        exclude_symbols,
        config,
        cache_dir,
        output_path,
        args.overwrite_cache,
    )


if __name__ == "__main__":
    main()
