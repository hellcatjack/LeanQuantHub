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


class CompositeTrendLowVol(QCAlgorithm):
    def initialize(self) -> None:
        params = self._load_params()
        selection = params.get("selection", {}) if isinstance(params.get("selection"), dict) else {}
        risk_params = params.get("risk", {}) if isinstance(params.get("risk"), dict) else {}
        defensive_params = (
            params.get("defensive", {}) if isinstance(params.get("defensive"), dict) else {}
        )
        blend_params = params.get("blend", {}) if isinstance(params.get("blend"), dict) else {}
        theme_weights = self._parse_json_param("theme_weights", params) or {}
        symbol_theme_map = self._parse_json_param("symbol_theme_map", params) or {}

        raw_symbols = self.get_parameter("symbols") or params.get("symbols")
        symbols = self._parse_symbol_list(raw_symbols)
        if not symbols:
            symbols = ["SPY", "QQQ", "NVDA", "AMD", "GOOGL", "TSLA"]

        self.target_momentum = int(selection.get("top_n_momentum", 10))
        self.target_lowvol = int(selection.get("top_n_lowvol", 20))
        self.min_positions = int(selection.get("min_positions", 6))
        self.max_position = float(risk_params.get("max_position", 0.2))
        self.inverse_vol = bool(risk_params.get("inverse_vol", True))
        self.min_vol = float(risk_params.get("min_vol", 0.01))
        self.theme_tilt = float(
            self.get_parameter("theme_tilt")
            or params.get("theme_tilt")
            or risk_params.get("theme_tilt")
            or 0.5
        )

        self.r4_days = int(selection.get("momentum_short_days", 63))
        self.r12_days = int(selection.get("momentum_long_days", 252))
        self.vol_days = int(selection.get("lowvol_days", 63))
        self.trend_weeks = int(selection.get("trend_weeks", 30))
        self.risk_on_weeks = int(selection.get("risk_on_weeks", 50))
        self.sma_days = max(50, self.trend_weeks * 5)
        self.risk_on_sma_days = max(50, self.risk_on_weeks * 5)
        self.lookback = max(self.r12_days, self.sma_days, self.vol_days, self.risk_on_sma_days)

        self.w12 = float(selection.get("momentum_12w", 0.7))
        self.w4 = float(selection.get("momentum_4w", 0.3))
        self.vol_penalty = float(selection.get("volatility_20d", 0.2))

        self.momentum_weight = float(blend_params.get("momentum_weight", 0.8))
        self.lowvol_weight = float(blend_params.get("lowvol_weight", 0.2))
        weight_total = self.momentum_weight + self.lowvol_weight
        if weight_total > 0:
            self.momentum_weight /= weight_total
            self.lowvol_weight /= weight_total

        self.defensive_symbols = self._parse_symbol_list(
            defensive_params.get("symbols", ["SHY", "IEF"])
        )
        if not self.defensive_symbols:
            self.defensive_symbols = ["SHY", "IEF"]

        self.theme_weights = {
            str(key).strip().upper(): float(value)
            for key, value in (theme_weights or {}).items()
            if str(key).strip()
        }
        self.symbol_theme_map = {
            str(key).strip().upper(): str(value).strip().upper()
            for key, value in (symbol_theme_map or {}).items()
            if str(key).strip() and str(value).strip()
        }

        self.set_start_date(2021, 1, 1)
        self.set_end_date(2025, 12, 26)
        self.set_cash(100000)
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
            self.date_rules.month_end(anchor),
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

        momentum_scores = []
        lowvol_scores = []
        vol_map = {}
        for symbol in self.symbols:
            window = self.windows.get(symbol)
            if window is None or window.count <= self.lookback:
                continue
            current = float(window[0])
            sma = sum(float(window[i]) for i in range(self.sma_days)) / self.sma_days
            if current <= sma:
                continue
            r4 = current / float(window[self.r4_days]) - 1.0
            r12 = current / float(window[self.r12_days]) - 1.0
            vol = self._calc_volatility(window, self.vol_days)
            vol_map[symbol] = vol
            score = self.w12 * r12 + self.w4 * r4 - self.vol_penalty * vol
            momentum_scores.append((score, symbol))
            if vol > 0:
                lowvol_scores.append((vol, symbol))

        momentum_scores.sort(reverse=True, key=lambda item: item[0])
        lowvol_scores.sort(key=lambda item: item[0])

        momentum_selected = [s for _, s in momentum_scores[: self.target_momentum]]
        lowvol_selected = [s for _, s in lowvol_scores[: self.target_lowvol]]

        if not momentum_selected and not lowvol_selected:
            self._allocate_defensive()
            return

        weights = {}
        if momentum_selected:
            per = self.momentum_weight / len(momentum_selected)
            for symbol in momentum_selected:
                weights[symbol] = weights.get(symbol, 0.0) + per
        if lowvol_selected:
            per = self.lowvol_weight / len(lowvol_selected)
            for symbol in lowvol_selected:
                weights[symbol] = weights.get(symbol, 0.0) + per
        if len(weights) < self.min_positions:
            self._allocate_defensive()
            return

        if self.inverse_vol:
            weights = self._apply_inverse_vol(weights, vol_map)
            if not weights:
                self._allocate_defensive()
                return
        weights = self._apply_theme_tilt(weights)
        if not weights:
            self._allocate_defensive()
            return

        targets = self._build_target_weights(weights)
        for symbol in self.symbols:
            target = targets.get(symbol, 0.0)
            if target > 0:
                self.set_holdings(symbol, target)
            elif self.portfolio[symbol].invested:
                self.liquidate(symbol)

        self._clear_defensive(set(targets.keys()))

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
        if window is None or window.count <= self.risk_on_sma_days:
            return True
        current = float(window[0])
        sma = sum(float(window[i]) for i in range(self.risk_on_sma_days)) / self.risk_on_sma_days
        return current >= sma

    def _load_params(self) -> dict:
        raw = self.get_parameter("algo_params")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _parse_json_param(self, key: str, params: dict) -> dict | None:
        raw = self.get_parameter(key) or params.get(key)
        if not raw:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            return {str(idx): item for idx, item in enumerate(raw)}
        try:
            return json.loads(str(raw))
        except json.JSONDecodeError:
            return None

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

    def _build_target_weights(self, weights: dict[Symbol, float]) -> dict[Symbol, float]:
        cleaned = {symbol: weight for symbol, weight in weights.items() if weight > 0}
        if not cleaned:
            return {}
        total = sum(cleaned.values())
        if total <= 0:
            return {}
        normalized = {symbol: weight / total for symbol, weight in cleaned.items()}

        cap = self.max_position
        if cap <= 0 or cap >= 1:
            return normalized
        if cap * len(normalized) < 0.999:
            cap = 1.0 / len(normalized)
        return self._apply_position_caps(normalized, cap)

    def _apply_inverse_vol(
        self, weights: dict[Symbol, float], vol_map: dict[Symbol, float]
    ) -> dict[Symbol, float]:
        adjusted: dict[Symbol, float] = {}
        for symbol, weight in weights.items():
            vol = vol_map.get(symbol)
            if vol is None or vol <= 0:
                vol = self.min_vol
            else:
                vol = max(vol, self.min_vol)
            adjusted[symbol] = weight / vol
        total = sum(adjusted.values())
        if total <= 0:
            return {}
        return {symbol: weight / total for symbol, weight in adjusted.items()}

    def _apply_theme_tilt(self, weights: dict[Symbol, float]) -> dict[Symbol, float]:
        if not weights or not self.theme_weights or not self.symbol_theme_map:
            return weights
        if self.theme_tilt <= 0:
            return weights
        theme_totals: dict[str, float] = {}
        for symbol, weight in weights.items():
            theme_key = self._get_symbol_theme(symbol)
            if not theme_key:
                continue
            theme_totals[theme_key] = theme_totals.get(theme_key, 0.0) + weight
        if not theme_totals:
            return weights
        desired_weights = self._normalize_theme_weights(theme_totals.keys())
        adjusted: dict[Symbol, float] = {}
        for symbol, weight in weights.items():
            theme_key = self._get_symbol_theme(symbol)
            if not theme_key:
                adjusted[symbol] = weight
                continue
            base = theme_totals.get(theme_key, 0.0)
            if base <= 0:
                adjusted[symbol] = weight
                continue
            desired = desired_weights.get(theme_key, base)
            factor = (1.0 - self.theme_tilt) + self.theme_tilt * (desired / base)
            adjusted[symbol] = weight * factor
        total = sum(adjusted.values())
        if total <= 0:
            return weights
        return {symbol: weight / total for symbol, weight in adjusted.items()}

    def _normalize_theme_weights(self, keys) -> dict[str, float]:
        filtered = {key: self.theme_weights.get(key, 0.0) for key in keys}
        total = sum(value for value in filtered.values() if value > 0)
        if total <= 0:
            return {key: 0.0 for key in keys}
        return {key: float(value) / total for key, value in filtered.items() if value > 0}

    def _get_symbol_theme(self, symbol: Symbol) -> str | None:
        key = None
        try:
            key = symbol.Value
        except AttributeError:
            key = str(symbol)
        key = str(key).strip().upper()
        if not key:
            return None
        return self.symbol_theme_map.get(key)

    @staticmethod
    def _apply_position_caps(
        weights: dict[Symbol, float], cap: float
    ) -> dict[Symbol, float]:
        remaining = dict(weights)
        capped: dict[Symbol, float] = {}
        target_total = 1.0
        while remaining:
            over = {symbol: weight for symbol, weight in remaining.items() if weight > cap}
            if not over:
                total_remaining = sum(remaining.values())
                if total_remaining <= 0:
                    break
                scale = target_total / total_remaining
                for symbol, weight in remaining.items():
                    capped[symbol] = weight * scale
                remaining = {}
                break
            for symbol in over:
                capped[symbol] = cap
            remaining = {symbol: weight for symbol, weight in remaining.items() if symbol not in over}
            target_total = 1.0 - sum(capped.values())
            if target_total <= 0:
                remaining = {}
                break
            total_remaining = sum(remaining.values())
            if total_remaining <= 0:
                remaining = {}
                break
            for symbol in list(remaining.keys()):
                remaining[symbol] = remaining[symbol] / total_remaining * target_total
        return capped
