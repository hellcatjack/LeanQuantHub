from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionEvent:
    order_id: int
    status: str
    exec_id: str | None
    filled: float
    avg_price: float | None


class IBExecutionClient:
    def __init__(self, host: str, port: int, client_id: int) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id

    def submit_orders(self, orders: list[object]) -> list[ExecutionEvent]:
        return []
