from __future__ import annotations

from app.services.ib_orders import submit_orders_mock
from app.services.ib_settings import resolve_ib_api_mode


class IBOrderExecutor:
    def __init__(self, settings_row) -> None:
        self.settings = settings_row
        self.api_mode = resolve_ib_api_mode(settings_row)

    def submit_orders(self, session, orders, *, price_map: dict[str, float] | None = None) -> dict:
        if self.api_mode == "mock":
            return submit_orders_mock(session, orders, price_map=price_map or {})
        # TODO: Replace with real IB order submission once ibapi is wired.
        return submit_orders_mock(session, orders, price_map=price_map or {})
