from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass
class FeatureConfig:
    return_windows: list[int]
    ma_windows: list[int]
    vol_windows: list[int]


def _safe_zscore(series: pd.Series) -> pd.Series:
    mean = series.rolling(20).mean()
    std = series.rolling(20).std()
    return (series - mean) / std.replace(0, np.nan)


def _drawdown(series: pd.Series, window: int) -> pd.Series:
    rolling_max = series.rolling(window).max()
    return 1 - series / rolling_max


def compute_features(
    df: pd.DataFrame, spy_df: pd.DataFrame, config: FeatureConfig
) -> pd.DataFrame:
    df = df.sort_index()
    spy_df = spy_df.sort_index()
    features = pd.DataFrame(index=df.index)

    close = df["close"]
    volume = df["volume"]
    returns = close.pct_change()

    for window in config.return_windows:
        features[f"ret_{window}"] = close.pct_change(window)

    for window in config.ma_windows:
        ma = close.rolling(window).mean()
        features[f"ma_bias_{window}"] = close / ma - 1

    for window in config.vol_windows:
        features[f"vol_{window}"] = returns.rolling(window).std()

    features["vol_z_20"] = _safe_zscore(volume)

    spy_close = spy_df["close"].reindex(df.index)
    features["rs_20"] = features.get("ret_20", close.pct_change(20)) - spy_close.pct_change(20)
    features["rs_60"] = features.get("ret_60", close.pct_change(60)) - spy_close.pct_change(60)

    ma_50 = close.rolling(50).mean()
    ma_200 = close.rolling(200).mean()
    features["trend_1"] = (close > ma_200).astype(int)
    features["trend_2"] = (ma_50 > ma_200).astype(int)

    features["dd_60"] = _drawdown(close, 60)
    features["ret_1"] = returns

    return features


def compute_label(df: pd.DataFrame, spy_df: pd.DataFrame, horizon: int) -> pd.Series:
    df = df.sort_index()
    spy_df = spy_df.sort_index()
    future = df["close"].shift(-horizon) / df["close"] - 1
    spy_future = spy_df["close"].shift(-horizon) / spy_df["close"] - 1
    spy_future = spy_future.reindex(df.index)
    return future - spy_future


def required_lookback(config: FeatureConfig, horizon: int) -> int:
    windows: Iterable[int] = list(config.return_windows) + list(config.ma_windows) + list(
        config.vol_windows
    )
    return max([200, horizon] + list(windows))
