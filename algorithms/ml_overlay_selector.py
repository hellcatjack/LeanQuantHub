from __future__ import annotations

import json
import os
from typing import Dict, List

import pandas as pd

from AlgorithmImports import *


class MLOverlaySelector(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(100000)

        raw_symbols = self.get_parameter("symbols") or "SPY,QQQ,NVDA,AMD,GOOGL,TSLA"
        self.symbols = self._parse_symbols(raw_symbols)
        self.benchmark_symbol = self.get_parameter("benchmark") or "SPY"
        if self.benchmark_symbol not in self.symbols:
            self.symbols.append(self.benchmark_symbol)

        self.top_n = int(self.get_parameter("top_n") or 10)
        self.rebalance_day = self.get_parameter("rebalance_day") or "Monday"

        self.model = self._load_model(self.get_parameter("ml_model_path"))
        self.features = self.model.get("features", [])
        self.coef = self.model.get("coef", [])
        self.intercept = float(self.model.get("intercept", 0.0))
        self.mean = self.model.get("mean", {})
        self.std = self.model.get("std", {})

        self.lookback = self._required_lookback()

        self.universe_settings.resolution = Resolution.DAILY
        for symbol in self.symbols:
            self.add_equity(symbol, Resolution.DAILY)
        self.set_benchmark(self.benchmark_symbol)

        day_map = {
            "Monday": DayOfWeek.Monday,
            "Tuesday": DayOfWeek.Tuesday,
            "Wednesday": DayOfWeek.Wednesday,
            "Thursday": DayOfWeek.Thursday,
            "Friday": DayOfWeek.Friday,
        }
        day_of_week = day_map.get(self.rebalance_day, DayOfWeek.Monday)
        self.schedule.on(
            self.date_rules.every(day_of_week),
            self.time_rules.after_market_open(self.benchmark_symbol, 30),
            self.rebalance,
        )

    def _load_model(self, path: str | None) -> Dict:
        if path:
            model_path = path
        else:
            model_path = os.path.join(os.getcwd(), "ml", "models", "linear_model.json")
        try:
            with open(model_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            self.debug(f"ML model not found: {model_path}")
            return {"features": [], "coef": [], "mean": {}, "std": {}, "intercept": 0.0}

    def _parse_symbols(self, raw: str) -> List[str]:
        return [s.strip().upper() for s in raw.split(",") if s.strip()]

    def _required_lookback(self) -> int:
        windows = [1, 5, 10, 20, 50, 60, 120, 200, 252]
        for name in self.features:
            if name.startswith("ret_") or name.startswith("ma_bias_") or name.startswith("vol_"):
                try:
                    windows.append(int(name.split("_")[1]))
                except ValueError:
                    continue
        return max(windows) + 5

    def rebalance(self) -> None:
        if not self.features:
            return
        spy_hist = self.history(self.benchmark_symbol, self.lookback, Resolution.DAILY)
        if spy_hist.empty:
            return
        spy_df = spy_hist.loc[self.benchmark_symbol]

        scores = []
        for symbol in self.symbols:
            if symbol == self.benchmark_symbol:
                continue
            hist = self.history(symbol, self.lookback, Resolution.DAILY)
            if hist.empty:
                continue
            df = hist.loc[symbol]
            features = self._compute_features(df, spy_df)
            if features is None:
                continue
            score = self._score(features)
            scores.append((symbol, score))

        if not scores:
            return
        scores.sort(key=lambda item: item[1], reverse=True)
        selected = [symbol for symbol, _ in scores[: max(self.top_n, 1)]]
        weight = 1.0 / len(selected)
        targets = [PortfolioTarget(symbol, weight) for symbol in selected]
        self.set_holdings(targets, True)

    def _score(self, features: Dict[str, float]) -> float:
        values = []
        for idx, name in enumerate(self.features):
            value = features.get(name)
            if value is None:
                return float("-inf")
            mean = float(self.mean.get(name, 0.0))
            std = float(self.std.get(name, 1.0)) or 1.0
            values.append((value - mean) / std)
        score = sum(values[i] * self.coef[i] for i in range(len(values)))
        return float(score + self.intercept)

    def _compute_features(self, df: pd.DataFrame, spy_df: pd.DataFrame) -> Dict[str, float] | None:
        close = df["close"]
        volume = df["volume"] if "volume" in df else None
        if len(close) < self.lookback:
            return None

        returns = close.pct_change()
        spy_close = spy_df["close"].reindex(close.index)

        features: Dict[str, float] = {}
        for name in self.features:
            if name.startswith("ret_"):
                window = int(name.split("_")[1])
                if len(close) <= window:
                    return None
                features[name] = close.iloc[-1] / close.iloc[-1 - window] - 1
            elif name.startswith("ma_bias_"):
                window = int(name.split("_")[2]) if name.count("_") >= 2 else int(name.split("_")[1])
                if len(close) < window:
                    return None
                ma = close.iloc[-window:].mean()
                features[name] = close.iloc[-1] / ma - 1 if ma else None
            elif name.startswith("vol_"):
                window = int(name.split("_")[1])
                if len(returns) < window:
                    return None
                features[name] = returns.iloc[-window:].std()
            elif name == "vol_z_20":
                if volume is None or len(volume) < 20:
                    return None
                mean = volume.iloc[-20:].mean()
                std = volume.iloc[-20:].std()
                features[name] = (volume.iloc[-1] - mean) / (std or 1.0)
            elif name == "rs_20":
                if len(close) < 20:
                    return None
                spy_ret = spy_close.pct_change(20).iloc[-1]
                features[name] = close.pct_change(20).iloc[-1] - spy_ret
            elif name == "rs_60":
                if len(close) < 60:
                    return None
                spy_ret = spy_close.pct_change(60).iloc[-1]
                features[name] = close.pct_change(60).iloc[-1] - spy_ret
            elif name == "trend_1":
                if len(close) < 200:
                    return None
                ma200 = close.iloc[-200:].mean()
                features[name] = 1.0 if close.iloc[-1] > ma200 else 0.0
            elif name == "trend_2":
                if len(close) < 200:
                    return None
                ma50 = close.iloc[-50:].mean()
                ma200 = close.iloc[-200:].mean()
                features[name] = 1.0 if ma50 > ma200 else 0.0
            elif name == "dd_60":
                if len(close) < 60:
                    return None
                rolling_max = close.iloc[-60:].max()
                features[name] = 1 - close.iloc[-1] / rolling_max if rolling_max else None
            elif name == "ret_1":
                features[name] = returns.iloc[-1]
            else:
                return None
        return features
