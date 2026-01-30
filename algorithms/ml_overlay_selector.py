from __future__ import annotations

import json
import os
from datetime import date as date_type
from datetime import datetime
from typing import Dict, List

import pandas as pd

from AlgorithmImports import *


class MLOverlaySelector(QCAlgorithm):
    def initialize(self) -> None:
        self.progress_start = datetime(2015, 1, 1)
        self.progress_end = datetime(2025, 12, 31)
        self.set_start_date(self.progress_start)
        self.set_end_date(self.progress_end)
        initial_cash = self.get_parameter("initial_cash")
        if initial_cash:
            try:
                self.set_cash(float(initial_cash))
            except ValueError:
                self.set_cash(30000)
        else:
            self.set_cash(30000)
        self.data_resolution = Resolution.DAILY

        raw_symbols = self.get_parameter("symbols") or "SPY,QQQ,NVDA,AMD,GOOGL,TSLA"
        self.symbols = self._parse_symbols(raw_symbols)
        self.benchmark_symbol = self.get_parameter("benchmark") or "SPY"
        if self.benchmark_symbol not in self.symbols:
            self.symbols.append(self.benchmark_symbol)

        self.top_n = int(self.get_parameter("top_n") or 10)
        self.rebalance_frequency = (self.get_parameter("rebalance_frequency") or "Daily").strip()
        self.rebalance_day = self.get_parameter("rebalance_day") or "Monday"
        self.rebalance_time_minutes = int(self.get_parameter("rebalance_time_minutes") or 30)
        self.weighting = (self.get_parameter("weighting") or "equal").strip().lower()
        min_score_raw = self.get_parameter("min_score")
        self.min_score = float(min_score_raw) if min_score_raw not in (None, "") else None
        max_weight_raw = self.get_parameter("max_weight")
        self.max_weight = float(max_weight_raw) if max_weight_raw not in (None, "") else None
        market_filter_raw = (self.get_parameter("market_filter") or "true").strip().lower()
        self.market_filter = market_filter_raw in ("1", "true", "yes", "y")
        self.market_ma_window = int(self.get_parameter("market_ma_window") or 200)
        self.risk_off_mode = (self.get_parameter("risk_off_mode") or "cash").strip().lower()

        self.model = self._load_model(self.get_parameter("ml_model_path"))
        self.features = self.model.get("features", [])
        self.coef = self.model.get("coef", [])
        self.intercept = float(self.model.get("intercept", 0.0))
        self.mean = self.model.get("mean", {})
        self.std = self.model.get("std", {})

        self.lookback = self._required_lookback()

        self.universe_settings.resolution = self.data_resolution
        for symbol in self.symbols:
            self.add_equity(symbol, self.data_resolution)
        self.set_benchmark(self.benchmark_symbol)
        if self.market_filter:
            self.sma_benchmark = self.SMA(
                self.benchmark_symbol, self.market_ma_window, self.data_resolution
            )
            self.set_warm_up(self.market_ma_window, self.data_resolution)
        else:
            self.sma_benchmark = None
        self.last_rebalance_date: date_type | None = None
        self.last_progress_date: date_type | None = None
        self.progress_total_days = max(
            (self.progress_end.date() - self.progress_start.date()).days,
            1,
        )

        day_map = {
            "Monday": DayOfWeek.Monday,
            "Tuesday": DayOfWeek.Tuesday,
            "Wednesday": DayOfWeek.Wednesday,
            "Thursday": DayOfWeek.Thursday,
            "Friday": DayOfWeek.Friday,
        }
        freq = self.rebalance_frequency.strip().lower()
        if freq == "daily":
            freq = "weekly"
            self.rebalance_frequency = "Weekly"
        if freq == "weekly":
            day_of_week = day_map.get(self.rebalance_day, DayOfWeek.Monday)
            date_rule = self.date_rules.every(day_of_week)
        elif freq == "monthly":
            date_rule = self.date_rules.month_start(self.benchmark_symbol)
        else:
            date_rule = self.date_rules.every_day(self.benchmark_symbol)
        self.schedule.on(
            date_rule,
            self.time_rules.after_market_open(self.benchmark_symbol, self.rebalance_time_minutes),
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

    def on_data(self, data: Slice) -> None:
        current_date = self.time.date()
        if self.last_progress_date == current_date:
            return
        self.last_progress_date = current_date
        elapsed_days = (current_date - self.progress_start.date()).days
        progress = min(max(elapsed_days / self.progress_total_days, 0.0), 1.0)
        self.debug(f"[progress] {current_date.isoformat()} {progress:.2%}")

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
        if self.last_rebalance_date == self.time.date():
            return
        self.last_rebalance_date = self.time.date()

        if self.market_filter:
            if not self.sma_benchmark or not self.sma_benchmark.IsReady:
                return
            if self.securities[self.benchmark_symbol].price < self.sma_benchmark.Current.Value:
                if self.risk_off_mode == "benchmark":
                    self.set_holdings(self.benchmark_symbol, 1.0)
                else:
                    self.liquidate()
                return

        if not self.features:
            return
        spy_hist = self.history(self.benchmark_symbol, self.lookback, self.data_resolution)
        if spy_hist.empty:
            return
        spy_df = spy_hist.loc[self.benchmark_symbol]

        scores = []
        for symbol in self.symbols:
            if symbol == self.benchmark_symbol:
                continue
            hist = self.history(symbol, self.lookback, self.data_resolution)
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
        selected: list[str] = []
        for symbol, score in scores:
            if self.min_score is not None and score < self.min_score:
                continue
            selected.append(symbol)
            if len(selected) >= max(self.top_n, 1):
                break
        selected = self._filter_tradable(selected)
        if not selected:
            return
        weights = self._build_weights(selected, dict(scores))
        if not weights:
            return
        targets = [PortfolioTarget(symbol, weight) for symbol, weight in weights.items()]
        self.set_holdings(targets, True)

    def _filter_tradable(self, symbols: list[str]) -> list[str]:
        tradable: list[str] = []
        for symbol in symbols:
            security = self.securities[symbol]
            if not security.IsTradable:
                continue
            if not security.HasData:
                continue
            if security.Price <= 0:
                continue
            tradable.append(symbol)
        return tradable

    def _build_weights(self, selected: list[str], scores: dict) -> dict[str, float]:
        if not selected:
            return {}
        if self.weighting == "score":
            min_score = self.min_score if self.min_score is not None else 0.0
            raw = [max(float(scores.get(symbol, 0.0)) - min_score, 0.0) for symbol in selected]
            total = sum(raw)
            if total <= 0:
                weights = {symbol: 1.0 / len(selected) for symbol in selected}
            else:
                weights = {symbol: raw[idx] / total for idx, symbol in enumerate(selected)}
        else:
            weights = {symbol: 1.0 / len(selected) for symbol in selected}

        if self.max_weight and self.max_weight > 0:
            weights = self._cap_and_normalize(weights, float(self.max_weight))
        return weights

    def _cap_and_normalize(self, weights: dict[str, float], cap: float) -> dict[str, float]:
        capped: dict[str, float] = {}
        remaining = dict(weights)
        for _ in range(len(remaining) + 1):
            over = {symbol: w for symbol, w in remaining.items() if w > cap}
            if not over:
                break
            for symbol in over:
                capped[symbol] = cap
                remaining.pop(symbol, None)
            remainder = 1.0 - sum(capped.values())
            if remainder <= 0 or not remaining:
                remaining = {}
                break
            total = sum(remaining.values())
            if total <= 0:
                remaining = {}
                break
            for symbol in list(remaining.keys()):
                remaining[symbol] = remaining[symbol] / total * remainder

        merged = {**remaining, **capped}
        total = sum(merged.values())
        if total > 0:
            merged = {symbol: weight / total for symbol, weight in merged.items()}
        return merged

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
