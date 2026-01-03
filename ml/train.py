from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from feature_engineering import FeatureConfig, compute_features, compute_label, required_lookback
from model_io import LinearModelPayload, save_linear_model


@dataclass
class Window:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_end: pd.Timestamp
    test_end: pd.Timestamp


def _parse_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _data_root_from_config(config: dict) -> Path:
    value = (config.get("data_root") or "").strip()
    if value:
        return Path(value)
    env_root = os.environ.get("DATA_ROOT", "")
    if env_root:
        return Path(env_root)
    return Path.cwd() / "data"


def _parse_dataset_name(path: Path) -> tuple[str, str]:
    stem = path.stem
    parts = stem.split("_", 1)
    dataset_name = parts[1] if len(parts) == 2 else stem
    tokens = dataset_name.split("_")
    vendor = tokens[0] if tokens else ""
    symbol = tokens[1] if len(tokens) > 1 else ""
    return vendor, symbol


def _count_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for _ in handle:
            count += 1
    return max(count - 1, 0)


def _pick_dataset_file(
    symbol: str, adjusted_dir: Path, vendor_preference: list[str]
) -> Path | None:
    symbol = symbol.upper()
    candidates = list(adjusted_dir.glob(f"*_{symbol}_*.csv"))
    if not candidates:
        candidates = list(adjusted_dir.glob(f"*_{symbol}.csv"))
    if not candidates:
        return None

    vendor_rank = {vendor.upper(): idx for idx, vendor in enumerate(vendor_preference)}
    best = None
    best_score = None

    for path in candidates:
        vendor, _ = _parse_dataset_name(path)
        rank = vendor_rank.get(vendor.upper(), len(vendor_rank) + 1)
        rows = _count_rows(path)
        score = (rank, -rows)
        if best_score is None or score < best_score:
            best = path
            best_score = score
    return best


def _load_series(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [col.strip().lower() for col in df.columns]
    if "date" not in df.columns:
        raise ValueError(f"missing date column: {path}")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["close"])
    df = df[~df.index.duplicated(keep="last")]
    return df


def _build_windows(
    dates: Iterable[pd.Timestamp], config: dict, warmup_days: int
) -> list[Window]:
    dates = sorted(set(dates))
    if not dates:
        return []
    start = dates[0] + pd.Timedelta(days=warmup_days)
    end = dates[-1]

    train_years = int(config["train_years"])
    valid_months = int(config["valid_months"])
    test_months = int(config["test_months"])
    step_months = int(config["step_months"])

    windows = []
    cursor = start
    while True:
        train_end = cursor
        train_start = train_end - pd.DateOffset(years=train_years)
        valid_end = train_end + pd.DateOffset(months=valid_months)
        test_end = valid_end + pd.DateOffset(months=test_months)
        if test_end > end:
            break
        windows.append(
            Window(
                train_start=train_start,
                train_end=train_end,
                valid_end=valid_end,
                test_end=test_end,
            )
        )
        cursor = cursor + pd.DateOffset(months=step_months)
    return windows


def _split_by_window(data: pd.DataFrame, window: Window) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train = data[(data.index >= window.train_start) & (data.index < window.train_end)]
    valid = data[(data.index >= window.train_end) & (data.index < window.valid_end)]
    test = data[(data.index >= window.valid_end) & (data.index < window.test_end)]
    return train, valid, test


def _standardize(
    df: pd.DataFrame, feature_cols: list[str]
) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    mean = df[feature_cols].mean().to_dict()
    std = df[feature_cols].std().replace(0, np.nan).to_dict()
    scaled = df.copy()
    for col in feature_cols:
        scaled[col] = (scaled[col] - mean[col]) / (std[col] if std[col] else 1.0)
    return scaled, mean, std


def _ridge_fit(x: np.ndarray, y: np.ndarray, l2: float) -> tuple[np.ndarray, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x = np.nan_to_num(x)
    y = np.nan_to_num(y)
    ones = np.ones((x.shape[0], 1))
    x_aug = np.hstack([x, ones])
    ridge = l2 * np.eye(x_aug.shape[1])
    coef = np.linalg.inv(x_aug.T @ x_aug + ridge) @ (x_aug.T @ y)
    return coef[:-1], float(coef[-1])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    diff = y_true - y_pred
    mae = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(diff**2)))
    corr = float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else 0.0
    return {"mae": mae, "rmse": rmse, "corr": corr}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ml/config.json")
    parser.add_argument("--data-root", default="")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = _parse_config(config_path)
    data_root = Path(args.data_root) if args.data_root else _data_root_from_config(config)
    adjusted_dir = data_root / "curated_adjusted"
    if not adjusted_dir.exists():
        raise RuntimeError(f"缺少目录: {adjusted_dir}")

    vendor_pref = config.get("vendor_preference", ["Alpha", "Stooq", "Lean"])
    benchmark_symbol = config.get("benchmark_symbol", "SPY")
    symbols = config.get("symbols", [])
    if benchmark_symbol not in symbols:
        symbols = [benchmark_symbol] + list(symbols)

    feature_windows = config.get("feature_windows", {})
    feat_config = FeatureConfig(
        return_windows=list(feature_windows.get("returns", [5, 10, 20, 60, 120, 252])),
        ma_windows=list(feature_windows.get("ma", [20, 60, 120, 200])),
        vol_windows=list(feature_windows.get("vol", [10, 20, 60])),
    )
    horizon = int(config.get("label_horizon_days", 20))

    spy_path = _pick_dataset_file(benchmark_symbol, adjusted_dir, vendor_pref)
    if not spy_path:
        raise RuntimeError(f"未找到基准数据: {benchmark_symbol}")
    spy_df = _load_series(spy_path)

    dataset = []
    for symbol in symbols:
        symbol_path = _pick_dataset_file(symbol, adjusted_dir, vendor_pref)
        if not symbol_path:
            continue
        df = _load_series(symbol_path)
        features = compute_features(df, spy_df, feat_config)
        label = compute_label(df, spy_df, horizon)
        merged = features.join(label.rename("label")).dropna()
        if merged.empty:
            continue
        merged["symbol"] = symbol
        dataset.append(merged)

    if not dataset:
        raise RuntimeError("未生成有效训练样本")

    data = pd.concat(dataset).sort_index()
    feature_cols = [col for col in data.columns if col not in {"label", "symbol"}]

    lookback = required_lookback(feat_config, horizon)
    windows = _build_windows(data.index, config.get("walk_forward", {}), lookback)
    if not windows:
        raise RuntimeError("无法生成 walk-forward 窗口，请检查时间跨度")

    output_dir = Path(config.get("output_dir", "ml/models"))
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_rows = []

    last_payload = None
    for idx, window in enumerate(windows, start=1):
        train_df, valid_df, test_df = _split_by_window(data, window)
        if train_df.empty or valid_df.empty:
            continue
        scaled_train, mean, std = _standardize(train_df, feature_cols)
        scaled_valid = valid_df.copy()
        for col in feature_cols:
            scaled_valid[col] = (scaled_valid[col] - mean[col]) / (std[col] if std[col] else 1.0)

        x_train = scaled_train[feature_cols].values
        y_train = scaled_train["label"].values
        l2 = float(config.get("model", {}).get("l2", 1e-4))
        coef, intercept = _ridge_fit(x_train, y_train, l2=l2)

        x_valid = scaled_valid[feature_cols].values
        y_valid = scaled_valid["label"].values
        y_pred = x_valid @ coef + intercept
        metric = _metrics(y_valid, y_pred)
        metrics_rows.append(
            {
                "window": idx,
                "train_start": window.train_start.date().isoformat(),
                "train_end": window.train_end.date().isoformat(),
                "valid_end": window.valid_end.date().isoformat(),
                "test_end": window.test_end.date().isoformat(),
                **metric,
            }
        )

        last_payload = LinearModelPayload(
            model_type="linear",
            features=feature_cols,
            coef=coef.tolist(),
            intercept=intercept,
            mean={k: float(v) for k, v in mean.items()},
            std={k: float(v) for k, v in std.items()},
            label_horizon_days=horizon,
            trained_at=datetime.utcnow().isoformat(),
            train_window={
                "train_start": window.train_start.date().isoformat(),
                "train_end": window.train_end.date().isoformat(),
                "valid_end": window.valid_end.date().isoformat(),
                "test_end": window.test_end.date().isoformat(),
            },
        )

    if not last_payload:
        raise RuntimeError("训练窗口不足，未生成模型")

    model_path = output_dir / "linear_model.json"
    save_linear_model(model_path, last_payload)

    metrics_path = output_dir / "metrics.csv"
    pd.DataFrame(metrics_rows).to_csv(metrics_path, index=False)
    print(f"saved model: {model_path}")
    print(f"saved metrics: {metrics_path}")


if __name__ == "__main__":
    main()
