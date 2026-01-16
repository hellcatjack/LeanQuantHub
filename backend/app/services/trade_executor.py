from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.db import SessionLocal
from app.models import TradeFill, TradeOrder, TradeRun
from pathlib import Path

from app.services.ib_market import fetch_market_snapshots
from app.services.job_lock import JobLock
from app.services.trade_orders import update_trade_order_status


@dataclass
class TradeExecutionResult:
    run_id: int
    status: str
    filled: int
    cancelled: int
    rejected: int
    skipped: int
    message: str | None
    dry_run: bool


def _pick_price(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    for key in ("last", "close", "bid", "ask"):
        value = snapshot.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _limit_allows_fill(side: str, price: float, limit_price: float) -> bool:
    if side == "BUY":
        return price <= limit_price
    if side == "SELL":
        return price >= limit_price
    return False


def execute_trade_run(
    run_id: int,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> TradeExecutionResult:
    session = SessionLocal()
    lock = JobLock("trade_execution", Path(settings.data_root) if settings.data_root else None)
    if not lock.acquire():
        session.close()
        raise RuntimeError("trade_execution_lock_busy")
    run: TradeRun | None = None
    try:
        run = session.get(TradeRun, run_id)
        if not run:
            raise RuntimeError("trade_run_not_found")
        if run.status not in {"queued", "blocked", "failed"}:
            raise RuntimeError("trade_run_status_invalid")
        if run.status != "queued" and not force:
            raise RuntimeError("trade_run_not_queued")

        orders = (
            session.query(TradeOrder)
            .filter(TradeOrder.run_id == run.id)
            .order_by(TradeOrder.id.asc())
            .all()
        )
        if not orders:
            run.status = "failed"
            run.message = "orders_empty"
            run.ended_at = datetime.utcnow()
            session.commit()
            return TradeExecutionResult(
                run_id=run.id,
                status=run.status,
                filled=0,
                cancelled=0,
                rejected=0,
                skipped=0,
                message=run.message,
                dry_run=dry_run,
            )

        run.status = "running"
        run.started_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.commit()

        symbols = sorted({order.symbol for order in orders})
        snapshots = fetch_market_snapshots(
            session,
            symbols=symbols,
            store=False,
            fallback_history=True,
            history_duration="5 D",
            history_bar_size="1 day",
            history_use_rth=True,
        )
        snapshot_map = {item.get("symbol"): item for item in snapshots}

        filled = 0
        cancelled = 0
        rejected = 0
        skipped = 0

        for order in orders:
            if order.status in {"FILLED", "CANCELED", "REJECTED"}:
                skipped += 1
                continue
            snapshot_item = snapshot_map.get(order.symbol) or {}
            snapshot = snapshot_item.get("data")
            price = _pick_price(snapshot)
            if price is None:
                rejected += 1
                if not dry_run:
                    update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "REJECTED",
                            "params": {"reason": "price_unavailable", "source": "mock"},
                        },
                    )
                continue

            side = (order.side or "").strip().upper()
            limit_price = order.limit_price
            should_fill = True
            if (order.order_type or "").upper() == "LMT":
                if limit_price is None:
                    should_fill = False
                else:
                    should_fill = _limit_allows_fill(side, price, float(limit_price))

            if not should_fill:
                cancelled += 1
                if not dry_run:
                    update_trade_order_status(
                        session,
                        order,
                        {
                            "status": "CANCELED",
                            "params": {"reason": "limit_not_reached", "source": "mock"},
                        },
                    )
                continue

            filled += 1
            if dry_run:
                continue
            update_trade_order_status(session, order, {"status": "SUBMITTED"})
            update_trade_order_status(
                session,
                order,
                {
                    "status": "FILLED",
                    "filled_quantity": order.quantity,
                    "avg_fill_price": price,
                    "params": {"source": "mock"},
                },
            )
            fill = TradeFill(
                order_id=order.id,
                fill_quantity=order.quantity,
                fill_price=price,
                commission=None,
                fill_time=datetime.utcnow(),
                params={"source": "mock"},
            )
            session.add(fill)
            session.commit()

        if dry_run:
            run.status = "queued"
            run.message = "dry_run_only"
            run.started_at = None
            run.updated_at = datetime.utcnow()
        else:
            if filled == 0:
                run.status = "failed"
            elif rejected or cancelled:
                run.status = "partial"
            else:
                run.status = "done"
            run.message = "executed_mock"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
        session.commit()

        return TradeExecutionResult(
            run_id=run.id,
            status=run.status,
            filled=filled,
            cancelled=cancelled,
            rejected=rejected,
            skipped=skipped,
            message=run.message,
            dry_run=dry_run,
        )
    except Exception as exc:
        if run is not None:
            run.status = "failed"
            run.message = f"execution_error:{exc}"
            run.ended_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
        raise
    finally:
        lock.release()
        session.close()
