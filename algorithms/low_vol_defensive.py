from __future__ import annotations

import json
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


class LowVolatilityDefensive(QCAlgorithm):
    def initialize(self) -> None:
        params = self._load_params()
        selection = params.get("selection", {}) if isinstance(params.get("selection"), dict) else {}
        risk_params = params.get("risk", {}) if isinstance(params.get("risk"), dict) else {}
        defensive_params = (
            params.get("defensive", {}) if isinstance(params.get("defensive"), dict) else {}
        )

        raw_symbols = self.get_parameter("symbols") or params.get("symbols")
        symbols = self._parse_symbol_list(raw_symbols)
        if not symbols:
            symbols = ["SPY", "QQQ", "NVDA", "AMD", "GOOGL", "TSLA"]

        self.target_positions = int(selection.get("top_n", 40))
        self.vol_days = int(selection.get("vol_days", 60))
        self.sma_days = max(50, int(selection.get("trend_weeks", 40)) * 5)
        self.lookback = max(self.vol_days, self.sma_days)
        self.max_position = float(risk_params.get("max_position", 0.06))

        self.defensive_symbols = self._parse_symbol_list(
            defensive_params.get("symbols", ["SHY", "IEF"])
        )
        if not self.defensive_symbols:
            self.defensive_symbols = ["SHY", "IEF"]

        self.set_start_date(2021, 1, 1)
        self.set_end_date(2025, 12, 26)
        initial_cash = self.get_parameter("initial_cash")
        if initial_cash:
            try:
                self.set_cash(float(initial_cash))
            except ValueError:
                self.set_cash(30000)
        else:
            self.set_cash(30000)
        self.settings.minimum_order_margin_portfolio_percentage = 0

        fee_bps = float(self.get_parameter("fee_bps") or 1.0)
        slippage_open_bps = float(self.get_parameter("slippage_open_bps") or 8.0)
        slippage_close_bps = float(self.get_parameter("slippage_close_bps") or slippage_open_bps)

        def _init_security(security: Security) -> None:
            security.set_fee_model(BpsFeeModel(fee_bps))
            security.set_fill_model(OpenCloseBpsFillModel(slippage_open_bps, slippage_close_bps))
            security.set_slippage_model(NullSlippageModel())

        self.set_security_initializer(_init_security)

        self.universe_settings.resolution = Resolution.DAILY
        self.windows = {}
        self.symbols = []
        self.symbol_lookup = {}
        self.defensive_assets = []
        self.benchmark_in_universe = False

        for symbol in symbols:
            equity = self.add_equity(symbol, Resolution.DAILY)
            self.symbols.append(equity.symbol)
            self.symbol_lookup[symbol.upper()] = equity.symbol
            self.windows[equity.symbol] = RollingWindow(self.lookback + 1)

        for symbol in self.defensive_symbols:
            existing = self.symbol_lookup.get(symbol.upper())
            if existing:
                self.defensive_assets.append(existing)
                continue
            equity = self.add_equity(symbol, Resolution.DAILY)
            self.defensive_assets.append(equity.symbol)
            self.symbol_lookup[symbol.upper()] = equity.symbol

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

        ranked = []
        for symbol in self.symbols:
            window = self.windows.get(symbol)
            if window is None or window.count <= self.lookback:
                continue
            current = float(window[0])
            sma = sum(float(window[i]) for i in range(self.sma_days)) / self.sma_days
            if current <= sma:
                continue
            vol = self._calc_volatility(window, self.vol_days)
            if vol <= 0:
                continue
            ranked.append((vol, symbol))

        ranked.sort(key=lambda item: item[0])
        selected = [symbol for _, symbol in ranked[: self.target_positions]]
        if not selected:
            self._allocate_defensive()
            return

        inv_vol = []
        for symbol in selected:
            vol = self._calc_volatility(self.windows[symbol], self.vol_days)
            if vol > 0:
                inv_vol.append((1.0 / vol, symbol))
        total_inv = sum(w for w, _ in inv_vol) or 1.0
        target_weights = {symbol: min(w / total_inv, self.max_position) for w, symbol in inv_vol}

        for symbol in self.symbols:
            target = target_weights.get(symbol, 0.0)
            if target > 0:
                self.set_holdings(symbol, target)
            elif self.portfolio[symbol].invested:
                self.liquidate(symbol)

        self._clear_defensive(set(target_weights.keys()))

    def _allocate_defensive(self) -> None:
        defensive = self._unique_symbols(self.defensive_assets)
        if not defensive:
            for symbol in self.symbols:
                if self.portfolio[symbol].invested:
                    self.liquidate(symbol)
            return
        per_weight = min(1.0 / len(defensive), self.max_position)
        defensive_set = set(defensive)
        for symbol in defensive:
            self.set_holdings(symbol, per_weight)
        for symbol in self.symbols:
            if symbol in defensive_set:
                continue
            if self.portfolio[symbol].invested:
                self.liquidate(symbol)

    def _clear_defensive(self, target_set: set[Symbol]) -> None:
        for symbol in self._unique_symbols(self.defensive_assets):
            if symbol in target_set:
                continue
            if self.portfolio[symbol].invested:
                self.liquidate(symbol)

    def _is_risk_on(self) -> bool:
        window = self.benchmark_window
        if window is None or window.count <= self.sma_days:
            return True
        current = float(window[0])
        sma = sum(float(window[i]) for i in range(self.sma_days)) / self.sma_days
        return current >= sma

    def _load_params(self) -> dict:
        raw = self.get_parameter("algo_params")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _parse_symbol_list(value) -> List[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip().upper() for item in value.split(",") if item.strip()]
        return []

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
