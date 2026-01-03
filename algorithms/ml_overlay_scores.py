from __future__ import annotations

import csv
import os
from bisect import bisect_right
from datetime import datetime
from typing import Dict, List
from pathlib import Path

from AlgorithmImports import *


class MLOverlayScores(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2015, 1, 1)
        self.set_end_date(2025, 12, 31)
        self.set_cash(100000)

        raw_symbols = self.get_parameter("symbols") or "SPY,QQQ,NVDA,AMD,GOOGL,TSLA"
        self.symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
        self.benchmark_symbol = self.get_parameter("benchmark") or "SPY"
        if self.benchmark_symbol not in self.symbols:
            self.symbols.append(self.benchmark_symbol)

        self.top_n = int(self.get_parameter("top_n") or 10)
        self.rebalance_day = self.get_parameter("rebalance_day") or "Monday"
        score_path = self.get_parameter("score_csv_path")
        if score_path:
            self.score_path = score_path
        else:
            root_dir = Path(__file__).resolve().parent.parent
            self.score_path = str(root_dir / "ml" / "models" / "scores.csv")

        self.scores_by_date, self.score_dates = self._load_scores(self.score_path)

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

    def rebalance(self) -> None:
        if not self.scores_by_date:
            return
        score_date = self._closest_score_date(self.time)
        if not score_date:
            return
        scores = self.scores_by_date.get(score_date, {})
        if not scores:
            return
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        selected = [symbol for symbol, _ in ranked if symbol in self.symbols and symbol != self.benchmark_symbol]
        selected = selected[: max(self.top_n, 1)]
        if not selected:
            return
        weight = 1.0 / len(selected)
        targets = [PortfolioTarget(symbol, weight) for symbol in selected]
        self.set_holdings(targets, True)
