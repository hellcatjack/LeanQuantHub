from __future__ import annotations

import csv
import os
from bisect import bisect_right
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Dict, List
from pathlib import Path

from AlgorithmImports import *


class MLOverlayScores(QCAlgorithm):
    def _parse_date_param(self, value: str | None, fallback: datetime) -> datetime:
        raw = str(value).strip() if value else ""
        if not raw:
            return fallback
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return fallback

    def _coerce_float_param(self, name: str, fallback: float) -> float:
        raw = self.get_parameter(name)
        if raw in (None, ""):
            return fallback
        try:
            return float(raw)
        except (TypeError, ValueError):
            return fallback

    def _set_runtime_stat(self, key: str, value: str) -> None:
        setter = getattr(self, "set_runtime_statistic", None)
        if setter:
            setter(key, value)
            return
        setter = getattr(self, "SetRuntimeStatistic", None)
        if setter:
            setter(key, value)

    def _portfolio_total_value(self) -> float:
        total = getattr(self.portfolio, "total_portfolio_value", None)
        if total is not None:
            return float(total)
        total = getattr(self, "Portfolio", None)
        if total is not None:
            return float(total.TotalPortfolioValue)
        return 0.0

    def _holding_value(self, symbol: str) -> float:
        holding = self.portfolio[symbol]
        value = getattr(holding, "holdings_value", None)
        if value is not None:
            return float(value)
        return float(getattr(holding, "HoldingsValue", 0.0))

    def _risk_off_exposure(self) -> float:
        if self.max_exposure <= 0:
            return 0.0
        return min(self.max_exposure, 1.0)

    def _apply_risk_off(self) -> None:
        exposure = self._risk_off_exposure()
        if exposure <= 0:
            self.liquidate()
            return
        if self.risk_off_mode == "benchmark":
            self.set_holdings(self.benchmark_symbol, exposure)
            return
        if self.risk_off_mode in ("defensive", "bond", "safe"):
            symbol = self.risk_off_symbol
            if symbol and symbol in self.securities:
                security = self.securities[symbol]
                if security.IsTradable and security.HasData and security.Price > 0:
                    self.set_holdings(symbol, exposure)
                    return
        self.liquidate()

    def initialize(self) -> None:
        start_raw = (
            self.get_parameter("backtest_start")
            or self.get_parameter("start_date")
            or self.get_parameter("start")
        )
        end_raw = (
            self.get_parameter("backtest_end")
            or self.get_parameter("end_date")
            or self.get_parameter("end")
        )
        self.progress_start = self._parse_date_param(start_raw, datetime(2015, 1, 1))
        self.progress_end = self._parse_date_param(end_raw, datetime(2025, 12, 31))
        if self.progress_end < self.progress_start:
            self.progress_end = self.progress_start
        self.set_start_date(self.progress_start)
        self.set_end_date(self.progress_end)
        self.set_cash(100000)
        self.data_resolution = Resolution.DAILY

        self.risk_off_mode = (self.get_parameter("risk_off_mode") or "cash").strip().lower()
        risk_off_symbol_raw = (
            self.get_parameter("risk_off_symbol")
            or self.get_parameter("defensive_symbol")
            or "SHY"
        )
        self.risk_off_symbol = risk_off_symbol_raw.strip().upper()

        raw_symbols = self.get_parameter("symbols") or "SPY,QQQ,NVDA,AMD,GOOGL,TSLA"
        self.symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
        self.benchmark_symbol = self.get_parameter("benchmark") or "SPY"
        if self.benchmark_symbol not in self.symbols:
            self.symbols.append(self.benchmark_symbol)
        if self.risk_off_symbol and self.risk_off_symbol not in self.symbols:
            self.symbols.append(self.risk_off_symbol)

        self.top_n = int(self.get_parameter("top_n") or 10)
        self.rebalance_frequency = (self.get_parameter("rebalance_frequency") or "Daily").strip()
        self.rebalance_day = self.get_parameter("rebalance_day") or "Monday"
        self.rebalance_time_minutes = int(self.get_parameter("rebalance_time_minutes") or 30)
        self.weighting = (self.get_parameter("weighting") or "equal").strip().lower()
        min_score_raw = self.get_parameter("min_score")
        self.min_score = float(min_score_raw) if min_score_raw not in (None, "") else None
        max_weight_raw = self.get_parameter("max_weight")
        self.max_weight = float(max_weight_raw) if max_weight_raw not in (None, "") else None
        max_exposure_raw = self.get_parameter("max_exposure")
        self.max_exposure = (
            float(max_exposure_raw) if max_exposure_raw not in (None, "") else 1.0
        )
        if self.max_exposure <= 0:
            self.max_exposure = 0.0
        if self.max_exposure > 1:
            self.max_exposure = 1.0
        market_filter_raw = (self.get_parameter("market_filter") or "true").strip().lower()
        self.market_filter = market_filter_raw in ("1", "true", "yes", "y")
        self.market_ma_window = int(self.get_parameter("market_ma_window") or 200)
        reload_scores_raw = (self.get_parameter("reload_scores") or "true").strip().lower()
        self.reload_scores = reload_scores_raw in ("1", "true", "yes", "y")
        score_delay_raw = self.get_parameter("score_delay_days") or 1
        try:
            self.score_delay_days = max(int(score_delay_raw), 0)
        except (TypeError, ValueError):
            self.score_delay_days = 1
        self.max_drawdown = max(self._coerce_float_param("max_drawdown", 0.12), 0.0)
        self.max_drawdown_52w = max(self._coerce_float_param("max_drawdown_52w", 0.12), 0.0)
        self.drawdown_recovery_ratio = self._coerce_float_param("drawdown_recovery_ratio", 0.9)
        if self.drawdown_recovery_ratio <= 0 or self.drawdown_recovery_ratio > 1:
            self.drawdown_recovery_ratio = 0.9
        self.max_turnover_week = max(self._coerce_float_param("max_turnover_week", 0.08), 0.0)
        self.vol_target = max(self._coerce_float_param("vol_target", 0.0), 0.0)
        self.vol_window = int(self._coerce_float_param("vol_window", 20))
        if self.vol_window < 5:
            self.vol_window = 5
        smoothing_raw = self.get_parameter("score_smoothing_alpha") or 0
        try:
            self.score_smoothing_alpha = max(float(smoothing_raw), 0.0)
        except (TypeError, ValueError):
            self.score_smoothing_alpha = 0.0
        if self.score_smoothing_alpha > 1:
            self.score_smoothing_alpha = 1.0
        carry_raw = (self.get_parameter("score_smoothing_carry") or "true").strip().lower()
        self.score_smoothing_carry = carry_raw in ("1", "true", "yes", "y")
        retain_raw = self.get_parameter("retain_top_n") or 0
        try:
            self.retain_top_n = max(int(retain_raw), 0)
        except (TypeError, ValueError):
            self.retain_top_n = 0
        self.smoothed_scores: Dict[str, float] = {}
        self.drawdown_locked = False
        self.peak_equity = None
        self.max_dd_all = 0.0
        self.max_dd_52w = 0.0
        self.current_dd_all = 0.0
        self.current_dd_52w = 0.0
        self.max_turnover_week_observed = 0.0
        self.equity_window: List[float] = []
        self.last_equity_date: date_type | None = None
        self.vol_scale = 1.0
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

    def _update_drawdown_stats(self) -> None:
        current_date = self.time.date()
        if self.last_equity_date == current_date:
            return
        self.last_equity_date = current_date
        equity = self._portfolio_total_value()
        if equity <= 0:
            return
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        if self.peak_equity:
            self.current_dd_all = max(0.0, 1.0 - equity / float(self.peak_equity))
            self.max_dd_all = max(self.max_dd_all, self.current_dd_all)
        self.equity_window.append(equity)
        if len(self.equity_window) > 252:
            self.equity_window = self.equity_window[-252:]
        peak_52w = max(self.equity_window) if self.equity_window else equity
        if peak_52w:
            self.current_dd_52w = max(0.0, 1.0 - equity / float(peak_52w))
            self.max_dd_52w = max(self.max_dd_52w, self.current_dd_52w)
        self._set_runtime_stat("MaxDD_all", f"{self.max_dd_all:.2%}")
        self._set_runtime_stat("MaxDD_52w", f"{self.max_dd_52w:.2%}")

    def _check_drawdown_guard(self, update_stats: bool = False) -> bool:
        if update_stats:
            self._update_drawdown_stats()
        drawdown_trigger = False
        if self.max_drawdown > 0 and self.current_dd_all >= self.max_drawdown:
            drawdown_trigger = True
        if self.max_drawdown_52w > 0 and self.current_dd_52w >= self.max_drawdown_52w:
            drawdown_trigger = True
        if self.drawdown_locked:
            dd_all_ok = (
                self.current_dd_all
                <= self.max_drawdown * self.drawdown_recovery_ratio
                if self.max_drawdown > 0
                else True
            )
            dd_52w_ok = (
                self.current_dd_52w
                <= self.max_drawdown_52w * self.drawdown_recovery_ratio
                if self.max_drawdown_52w > 0
                else True
            )
            if dd_all_ok and dd_52w_ok:
                self.drawdown_locked = False
            else:
                drawdown_trigger = True
        if not drawdown_trigger:
            return False
        self.drawdown_locked = True
        self._apply_risk_off()
        return True

    def _update_vol_scale(self) -> None:
        if self.vol_target <= 0:
            self.vol_scale = 1.0
            return
        history = self.History(self.benchmark_symbol, self.vol_window + 1, Resolution.Daily)
        if history is None:
            self.vol_scale = 1.0
            return
        if not hasattr(history, "empty") or history.empty:
            self.vol_scale = 1.0
            return
        close_series = history.loc[self.benchmark_symbol]["close"]
        returns = close_series.pct_change().dropna()
        if returns.empty:
            self.vol_scale = 1.0
            return
        vol = float(returns.std()) * (252 ** 0.5)
        if vol <= 0:
            self.vol_scale = 1.0
            return
        scale = min(self.vol_target / vol, 1.0)
        self.vol_scale = max(scale, 0.0)
        self._set_runtime_stat("VolScale", f"{self.vol_scale:.2%}")

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
        target = current - timedelta(days=self.score_delay_days)
        idx = bisect_right(self.score_dates, target) - 1
        if idx < 0:
            return None
        date = self.score_dates[idx]
        return date.strftime("%Y-%m-%d")

    def on_data(self, data: Slice) -> None:
        current_date = self.time.date()
        if self.last_progress_date == current_date:
            return
        self.last_progress_date = current_date
        self._update_drawdown_stats()
        self._check_drawdown_guard()
        elapsed_days = (current_date - self.progress_start.date()).days
        progress = min(max(elapsed_days / self.progress_total_days, 0.0), 1.0)
        self.debug(f"[progress] {current_date.isoformat()} {progress:.2%}")

    def rebalance(self) -> None:
        if self.last_rebalance_date == self.time.date():
            return
        self.last_rebalance_date = self.time.date()
        if self._check_drawdown_guard(update_stats=True):
            return

        if self.market_filter:
            if not self.sma_benchmark or not self.sma_benchmark.IsReady:
                return
            if self.securities[self.benchmark_symbol].price < self.sma_benchmark.Current.Value:
                self._apply_risk_off()
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
        scores_used = scores
        if self.score_smoothing_alpha > 0:
            updated: Dict[str, float] = {}
            for symbol, score in scores.items():
                prev = self.smoothed_scores.get(symbol, score)
                updated[symbol] = self.score_smoothing_alpha * score + (
                    1 - self.score_smoothing_alpha
                ) * prev
            if self.score_smoothing_carry:
                for symbol, prev in self.smoothed_scores.items():
                    updated.setdefault(symbol, prev)
            self.smoothed_scores = updated
            scores_used = updated if self.score_smoothing_carry else {
                symbol: updated[symbol] for symbol in scores
            }

        ranked = sorted(scores_used.items(), key=lambda item: item[1], reverse=True)
        selected: list[str] = []
        if self.retain_top_n > 0:
            buffer_limit = max(self.top_n + self.retain_top_n, self.top_n)
            buffer_set = {symbol for symbol, _ in ranked[:buffer_limit]}
            for symbol in self.symbols:
                if symbol == self.benchmark_symbol or symbol == self.risk_off_symbol:
                    continue
                if not self.portfolio[symbol].Invested:
                    continue
                if symbol not in buffer_set:
                    continue
                selected.append(symbol)
                if len(selected) >= max(self.top_n, 1):
                    break
        for symbol, score in ranked:
            if len(selected) >= max(self.top_n, 1):
                break
            if symbol in selected:
                continue
            if symbol not in self.symbols or symbol in (self.benchmark_symbol, self.risk_off_symbol):
                continue
            if self.min_score is not None and score < self.min_score:
                continue
            selected.append(symbol)
        selected = self._filter_tradable(selected)
        if not selected:
            return
        weights = self._build_weights(selected, scores_used)
        if not weights:
            return
        self._update_vol_scale()
        if self.vol_scale < 1.0:
            weights = {symbol: weight * self.vol_scale for symbol, weight in weights.items()}
        if self.max_turnover_week > 0:
            total_value = self._portfolio_total_value()
            current_weights: Dict[str, float] = {}
            if total_value > 0:
                for symbol in self.symbols:
                    if symbol == self.benchmark_symbol:
                        continue
                    holding_value = self._holding_value(symbol)
                    if holding_value == 0:
                        continue
                    current_weights[symbol] = holding_value / total_value
            symbols = set(current_weights.keys()) | set(weights.keys())
            turnover = 0.0
            for symbol in symbols:
                turnover += abs(weights.get(symbol, 0.0) - current_weights.get(symbol, 0.0))
            turnover *= 0.5
            if turnover > self.max_turnover_week and turnover > 0:
                scale = self.max_turnover_week / turnover
                adjusted: Dict[str, float] = {}
                for symbol in symbols:
                    current_w = current_weights.get(symbol, 0.0)
                    target_w = weights.get(symbol, 0.0)
                    new_w = current_w + (target_w - current_w) * scale
                    if new_w != 0.0:
                        adjusted[symbol] = new_w
                weights = adjusted
                turnover = self.max_turnover_week
            self.max_turnover_week_observed = max(self.max_turnover_week_observed, turnover)
            self._set_runtime_stat("Turnover_week", f"{turnover:.2%}")
            self._set_runtime_stat(
                "MaxTurnover_week", f"{self.max_turnover_week_observed:.2%}"
            )
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
        if self.max_exposure < 1.0:
            weights = {symbol: weight * self.max_exposure for symbol, weight in weights.items()}
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
