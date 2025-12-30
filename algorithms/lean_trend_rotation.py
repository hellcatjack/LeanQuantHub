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
        costs = self._load_costs(project_root / "configs" / "config.json")

        if not symbols:
            raise ValueError("No symbols loaded for trend rotation strategy.")

        self.symbols = []
        self.target_positions = 8

        self.r3_days = 63
        self.r6_days = 126
        self.r12_days = 252
        self.sma_days = 200
        self.lookback = max(self.r12_days, self.sma_days)

        self.w3 = 0.3
        self.w6 = 0.5
        self.w12 = 0.2

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
            self.windows[equity.symbol] = RollingWindow(self.lookback + 1)

        self.set_warm_up(self.lookback + 1, Resolution.DAILY)
        self.set_benchmark(self.symbols[0])

        anchor = self.symbols[0]
        self.schedule.on(
            self.date_rules.week_end(anchor),
            self.time_rules.after_market_close(anchor, 0),
            self.rebalance,
        )

    def on_data(self, data) -> None:
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

        scored = []
        for symbol in self.symbols:
            window = self.windows.get(symbol)
            if window is None or window.count <= self.lookback:
                continue

            current = float(window[0])
            r3 = current / float(window[self.r3_days]) - 1.0
            r6 = current / float(window[self.r6_days]) - 1.0
            r12 = current / float(window[self.r12_days]) - 1.0
            sma = sum(float(window[i]) for i in range(self.sma_days)) / self.sma_days

            if current <= sma:
                continue

            score = self.w3 * r3 + self.w6 * r6 + self.w12 * r12
            scored.append((score, symbol))

        scored.sort(reverse=True, key=lambda item: item[0])
        selected = [symbol for _, symbol in scored[: self.target_positions]]
        selected_set = set(selected)

        if not selected:
            for symbol in self.symbols:
                if self.portfolio[symbol].invested:
                    self.liquidate(symbol)
            return

        weight = 1.0 / len(selected)
        for symbol in self.symbols:
            if symbol in selected_set:
                self.set_holdings(symbol, weight)
            elif self.portfolio[symbol].invested:
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
