from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List

from AlgorithmImports import *


class BpsFeeModel(FeeModel):
    def __init__(self, fee_bps: float, currency: str = "USD") -> None:
        super().__init__()
        self.fee_rate = fee_bps / 10000.0
        self.currency = currency

    def get_order_fee(self, parameters: OrderFeeParameters) -> OrderFee:
        price = float(parameters.security.price)
        if price <= 0:
            return OrderFee(CashAmount(0, self.currency))
        value = price * float(parameters.order.absolute_quantity)
        fee = value * self.fee_rate
        return OrderFee(CashAmount(fee, self.currency))


class OpenCloseBpsFillModel(EquityFillModel):
    def __init__(self, open_bps: float, close_bps: float) -> None:
        super().__init__()
        self.open_rate = max(0.0, open_bps) / 10000.0
        self.close_rate = max(0.0, close_bps) / 10000.0

    def market_fill(self, asset: Security, order: MarketOrder) -> OrderEvent:
        fill = super().market_fill(asset, order)
        return self._apply_bps(fill, order, self.open_rate)

    def market_on_open_fill(self, asset: Security, order: MarketOnOpenOrder) -> OrderEvent:
        fill = super().market_on_open_fill(asset, order)
        return self._apply_bps(fill, order, self.open_rate)

    def market_on_close_fill(self, asset: Security, order: MarketOnCloseOrder) -> OrderEvent:
        fill = super().market_on_close_fill(asset, order)
        return self._apply_bps(fill, order, self.close_rate)

    @staticmethod
    def _apply_bps(fill: OrderEvent, order: Order, rate: float) -> OrderEvent:
        if fill.status != OrderStatus.FILLED:
            return fill
        if rate <= 0:
            return fill
        if fill.fill_price <= 0:
            return fill
        direction = 1.0 if order.direction == OrderDirection.BUY else -1.0
        fill.fill_price *= 1.0 + direction * rate
        return fill


class TrendRotationAlgorithm(QCAlgorithm):
    def initialize(self) -> None:
        project_root = Path(__file__).resolve().parent
        symbols = self._load_symbols(project_root / "configs" / "universe_us_tech.csv")
        if not symbols:
            fallback = self.get_parameter("symbols") or "SPY,QQQ,NVDA,AMD,GOOGL,TSLA"
            symbols = [item.strip().upper() for item in fallback.split(",") if item.strip()]
        costs = self._load_costs(project_root / "configs" / "config.json")

        if not symbols:
            raise ValueError("No symbols loaded for trend rotation strategy.")

        params = self._load_params()
        selection = params.get("selection", {}) if isinstance(params.get("selection"), dict) else {}
        core_params = params.get("core", {}) if isinstance(params.get("core"), dict) else {}
        risk_params = params.get("risk", {}) if isinstance(params.get("risk"), dict) else {}
        defensive_params = (
            params.get("defensive", {}) if isinstance(params.get("defensive"), dict) else {}
        )

        self.symbols = []
        self.symbol_lookup = {}
        self.target_positions = int(selection.get("top_n", 6))
        self.core_symbols = [
            str(item).upper()
            for item in core_params.get("symbols", ["NVDA", "AMD", "GOOGL", "TSLA"])
            if str(item).strip()
        ]
        self.core_weight = float(core_params.get("total_weight", 0.5))
        self.core_redistribute = str(core_params.get("redistribute", "cash"))
        self.max_position = float(risk_params.get("max_position", 0.25))
        self.defensive_symbols = [
            str(item).upper()
            for item in defensive_params.get("symbols", ["SHY", "IEF"])
            if str(item).strip()
        ]
        self.defensive_assets = []
        self.benchmark_in_universe = False

        self.r4_days = 20
        self.r12_days = 60
        self.vol_days = 20
        self.sma_days = max(50, int(selection.get("trend_weeks", 20)) * 5)
        self.lookback = max(self.r12_days, self.sma_days, self.vol_days)

        self.w12 = float(selection.get("momentum_12w", 0.6))
        self.w4 = float(selection.get("momentum_4w", 0.4))
        self.vol_penalty = float(selection.get("volatility_20d", 0.3))

        self.set_start_date(2021, 1, 1)
        self.set_end_date(2025, 12, 26)
        self.set_cash(100000)
        self.settings.minimum_order_margin_portfolio_percentage = 0

        fee_bps = float(self.get_parameter("fee_bps") or costs.get("fee_bps", 1.0))
        slippage_open_bps = float(
            self.get_parameter("slippage_open_bps")
            or costs.get("slippage_open_bps", costs.get("slippage_bps", 8.0))
        )
        slippage_close_bps = float(
            self.get_parameter("slippage_close_bps")
            or costs.get("slippage_close_bps", costs.get("slippage_bps", slippage_open_bps))
        )
        def _init_security(security: Security) -> None:
            security.set_fee_model(BpsFeeModel(fee_bps))
            security.set_fill_model(OpenCloseBpsFillModel(slippage_open_bps, slippage_close_bps))
            security.set_slippage_model(NullSlippageModel())

        self.set_security_initializer(_init_security)

        self.universe_settings.resolution = Resolution.DAILY
        self.windows = {}
        for symbol in symbols:
            equity = self.add_equity(symbol, Resolution.DAILY)
            self.symbols.append(equity.symbol)
            self.symbol_lookup[symbol.upper()] = equity.symbol
            self.windows[equity.symbol] = RollingWindow(self.lookback + 1)

        for symbol in self.defensive_symbols:
            existing = self.symbol_lookup.get(symbol)
            if existing:
                self.defensive_assets.append(existing)
                continue
            equity = self.add_equity(symbol, Resolution.DAILY)
            self.defensive_assets.append(equity.symbol)
            self.symbol_lookup[symbol] = equity.symbol

        self.set_warm_up(self.lookback + 1, Resolution.DAILY)
        benchmark = (self.get_parameter("benchmark") or "SPY").strip().upper()
        self.benchmark_symbol = self.symbol_lookup.get(benchmark)
        if self.benchmark_symbol and self.benchmark_symbol in self.windows:
            self.benchmark_in_universe = True
            self.benchmark_window = self.windows[self.benchmark_symbol]
        else:
            bench_equity = self.add_equity(benchmark, Resolution.DAILY)
            self.benchmark_symbol = bench_equity.symbol
            self.benchmark_window = RollingWindow(self.lookback + 1)
        self.set_benchmark(self.benchmark_symbol)

        anchor = self.benchmark_symbol or self.symbols[0]
        self.schedule.on(
            self.date_rules.week_end(anchor),
            self.time_rules.after_market_close(anchor, 0),
            self.rebalance,
        )

    def on_data(self, data) -> None:
        if not self.benchmark_in_universe:
            if self.benchmark_symbol and data.contains_key(self.benchmark_symbol):
                bench_bar = data[self.benchmark_symbol]
                if bench_bar is not None:
                    self.benchmark_window.add(bench_bar.close)
        for symbol in self.symbols:
            if not data.contains_key(symbol):
                continue
            bar = data[symbol]
            if bar is None:
                continue
            self.windows[symbol].add(bar.close)

    def rebalance(self) -> None:
        if self.is_warming_up:
            return

        if not self._is_risk_on():
            self._allocate_defensive()
            return

        scored = []
        for symbol in self.symbols:
            window = self.windows.get(symbol)
            if window is None or window.count <= self.lookback:
                continue

            current = float(window[0])
            r4 = current / float(window[self.r4_days]) - 1.0
            r12 = current / float(window[self.r12_days]) - 1.0
            sma = sum(float(window[i]) for i in range(self.sma_days)) / self.sma_days

            if current <= sma:
                continue

            vol = self._calc_volatility(window, self.vol_days)
            score = self.w12 * r12 + self.w4 * r4 - self.vol_penalty * vol
            scored.append((score, symbol))

        scored.sort(reverse=True, key=lambda item: item[0])
        selected = [symbol for _, symbol in scored[: self.target_positions]]
        selected_set = set(selected)

        if not selected:
            for symbol in self.symbols:
                if self.portfolio[symbol].invested:
                    self.liquidate(symbol)
            return

        core_selected = [s for s in selected if s.Value in self.core_symbols]
        non_core = [s for s in selected if s.Value not in self.core_symbols]
        target_weights = {}

        core_weight_total = self.core_weight if core_selected else 0.0
        if core_selected:
            core_weight_each = core_weight_total / len(core_selected)
            for symbol in core_selected:
                target_weights[symbol] = core_weight_each

        remaining = 1.0 - core_weight_total
        if non_core and remaining > 0:
            per = remaining / len(non_core)
            for symbol in non_core:
                target_weights[symbol] = per
        elif core_selected and self.core_redistribute == "core":
            extra = remaining / len(core_selected) if core_selected else 0.0
            for symbol in core_selected:
                target_weights[symbol] = target_weights.get(symbol, 0.0) + extra

        for symbol in self.symbols:
            target = min(target_weights.get(symbol, 0.0), self.max_position)
            if target > 0:
                self.set_holdings(symbol, target)
            elif self.portfolio[symbol].invested:
                self.liquidate(symbol)

        if self.defensive_assets:
            target_set = set(target_weights.keys())
            for symbol in self._unique_symbols(self.defensive_assets):
                if symbol in target_set:
                    continue
                if self.portfolio[symbol].invested:
                    self.liquidate(symbol)

    @staticmethod
    def _load_symbols(path: Path) -> List[str]:
        if not path.exists():
            return []
        symbols: List[str] = []
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                active = row.get("active", "1")
                if str(active).strip() != "1":
                    continue
                symbol = row.get("symbol", "").strip()
                if symbol:
                    symbols.append(symbol)
        return symbols

    @staticmethod
    def _load_costs(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("costs", {})
        except json.JSONDecodeError:
            return {}

    def _load_params(self) -> dict:
        raw = self.get_parameter("algo_params")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _is_risk_on(self) -> bool:
        window = self.benchmark_window
        if window is None or window.count <= self.sma_days:
            return True
        current = float(window[0])
        sma = sum(float(window[i]) for i in range(self.sma_days)) / self.sma_days
        return current >= sma

    @staticmethod
    def _calc_volatility(window: RollingWindow, days: int) -> float:
        if window.count <= days:
            return 0.0
        returns = []
        for i in range(days):
            today = float(window[i])
            prev = float(window[i + 1])
            if prev <= 0:
                continue
            returns.append(today / prev - 1.0)
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5

    def _allocate_defensive(self) -> None:
        defensive = self._unique_symbols(self.defensive_assets)
        if not defensive:
            for symbol in self.symbols:
                if self.portfolio[symbol].invested:
                    self.liquidate(symbol)
            return

        per_weight = 1.0 / len(defensive)
        defensive_set = set(defensive)

        for symbol in defensive:
            weight = min(per_weight, self.max_position)
            if weight > 0:
                self.set_holdings(symbol, weight)

        for symbol in self.symbols:
            if symbol in defensive_set:
                continue
            if self.portfolio[symbol].invested:
                self.liquidate(symbol)

    @staticmethod
    def _unique_symbols(symbols: List[Symbol]) -> List[Symbol]:
        unique = []
        seen = set()
        for symbol in symbols:
            if symbol in seen:
                continue
            seen.add(symbol)
            unique.append(symbol)
        return unique
