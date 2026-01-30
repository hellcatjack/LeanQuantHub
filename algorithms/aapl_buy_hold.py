from AlgorithmImports import *


class AaplBuyHold(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2025, 12, 26)
        initial_cash = self.get_parameter("initial_cash")
        if initial_cash:
            try:
                self.set_cash(float(initial_cash))
            except ValueError:
                self.set_cash(30000)
        else:
            self.set_cash(30000)

        equity = self.add_equity("AAPL", Resolution.DAILY)
        self.symbol = equity.symbol
        benchmark = (self.get_parameter("benchmark") or "").strip()
        if benchmark:
            self.set_benchmark(benchmark)
        else:
            self.set_benchmark(self.symbol)

    def on_data(self, data) -> None:
        if self.portfolio[self.symbol].invested:
            return
        if data.contains_key(self.symbol):
            self.set_holdings(self.symbol, 1.0)
