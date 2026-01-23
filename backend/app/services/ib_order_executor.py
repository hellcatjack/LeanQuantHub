from __future__ import annotations

from app.models import IBSettings
from app.services.ib_execution import IBExecutionClient
from app.services.ib_orders import submit_orders_mock
from app.services.ib_settings import resolve_ib_api_mode


def submit_orders_real(session, orders, *, price_map: dict[str, float] | None = None) -> dict:
    settings = session.query(IBSettings).first()
    if settings is None:
        return {"filled": 0, "rejected": len(orders), "cancelled": 0}
    client = IBExecutionClient(settings.host, settings.port, settings.client_id)
    events = client.submit_orders(list(orders))
    filled = sum(1 for event in events if (event.status or "").upper() in {"FILLED", "PARTIAL"})
    rejected = sum(1 for event in events if (event.status or "").upper() == "REJECTED")
    cancelled = sum(1 for event in events if (event.status or "").upper() == "CANCELED")
    return {"filled": filled, "rejected": rejected, "cancelled": cancelled}


class IBOrderExecutor:
    def __init__(self, settings_row) -> None:
        self.settings = settings_row
        self.api_mode = resolve_ib_api_mode(settings_row)

    def submit_orders(self, session, orders, *, price_map: dict[str, float] | None = None) -> dict:
        if self.api_mode == "ib":
            return submit_orders_real(session, orders, price_map=price_map)
        return submit_orders_mock(session, orders, price_map=price_map or {})
