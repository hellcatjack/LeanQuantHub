from AlgorithmImports import *


class AaplBuyHold(QCAlgorithm):
    def initialize(self) -> None:
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2025, 12, 26)
        self.set_cash(100000)

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
