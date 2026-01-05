from __future__ import annotations

import csv
import os
from bisect import bisect_right
from datetime import date as date_type
from datetime import datetime
from typing import Dict, List
from pathlib import Path

from AlgorithmImports import *


class MLOverlayScores(QCAlgorithm):
    def initialize(self) -> None:
        self.progress_start = datetime(2015, 1, 1)
        self.progress_end = datetime(2025, 12, 31)
        self.set_start_date(self.progress_start)
        self.set_end_date(self.progress_end)
        self.set_cash(100000)
        self.data_resolution = Resolution.DAILY

        raw_symbols = self.get_parameter("symbols") or "SPY,QQQ,NVDA,AMD,GOOGL,TSLA"
        self.symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
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
        reload_scores_raw = (self.get_parameter("reload_scores") or "true").strip().lower()
        self.reload_scores = reload_scores_raw in ("1", "true", "yes", "y")
        score_path = self.get_parameter("score_csv_path")
        if score_path:
            self.score_path = score_path
        else:
            root_dir = Path(__file__).resolve().parent.parent
            self.score_path = str(root_dir / "ml" / "models" / "scores.csv")

        self.scores_by_date, self.score_dates = self._load_scores(self.score_path)

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

    def _load_scores(self, path: str) -> tuple[Dict[str, Dict[str, float]], List[datetime]]:
        scores: Dict[str, Dict[str, float]] = {}
        dates: List[datetime] = []
        if not os.path.exists(path):
            self.debug(f"Score file missing: {path}")
            return scores, dates
        with open(path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                date_str = (row.get("date") or "").strip()
                symbol = (row.get("symbol") or "").strip().upper()
                if not date_str or not symbol:
                    continue
                try:
                    score = float(row.get("score", ""))
                except ValueError:
                    continue
                scores.setdefault(date_str, {})[symbol] = score
        for date_str in sorted(scores.keys()):
            try:
                dates.append(datetime.strptime(date_str, "%Y-%m-%d"))
            except ValueError:
                continue
        return scores, dates

    def _closest_score_date(self, current: datetime) -> str | None:
        if not self.score_dates:
            return None
        idx = bisect_right(self.score_dates, current) - 1
        if idx < 0:
            return None
        date = self.score_dates[idx]
        return date.strftime("%Y-%m-%d")

    def on_data(self, data: Slice) -> None:
        current_date = self.time.date()
        if self.last_progress_date == current_date:
            return
        self.last_progress_date = current_date
        elapsed_days = (current_date - self.progress_start.date()).days
        progress = min(max(elapsed_days / self.progress_total_days, 0.0), 1.0)
        self.debug(f"[progress] {current_date.isoformat()} {progress:.2%}")

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

        if self.reload_scores:
            self.scores_by_date, self.score_dates = self._load_scores(self.score_path)
        if not self.scores_by_date:
            return
        score_date = self._closest_score_date(self.time)
        if not score_date:
            return
        scores = self.scores_by_date.get(score_date, {})
        if not scores:
            return
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        selected: list[str] = []
        for symbol, score in ranked:
            if symbol not in self.symbols or symbol == self.benchmark_symbol:
                continue
            if self.min_score is not None and score < self.min_score:
                continue
            selected.append(symbol)
            if len(selected) >= max(self.top_n, 1):
                break
        selected = self._filter_tradable(selected)
        if not selected:
            return
        weights = self._build_weights(selected, scores)
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
