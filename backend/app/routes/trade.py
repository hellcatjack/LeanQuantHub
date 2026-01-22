from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.models import TradeGuardState, TradeOrder, TradeRun, TradeSettings
from app.schemas import (
    TradeOrderCreate,
    TradeOrderOut,
    TradeOrderStatusUpdate,
    TradeRunCreate,
    TradeRunExecuteOut,
    TradeRunExecuteRequest,
    TradeRunOut,
    TradeSettingsOut,
    TradeSettingsUpdate,
    TradeGuardEvaluateOut,
    TradeGuardEvaluateRequest,
    TradeGuardStateOut,
)
from app.services.audit_log import record_audit
from app.services.ib_market import check_market_health
from app.services.trade_guard import evaluate_intraday_guard, get_or_create_guard_state
from app.services.trade_executor import execute_trade_run
from app.services.trade_orders import create_trade_order, update_trade_order_status

router = APIRouter(prefix="/api/trade", tags=["trade"])


@router.get("/settings", response_model=TradeSettingsOut)
def get_trade_settings():
    with get_session() as session:
        settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
        if settings_row is None:
            settings_row = TradeSettings(risk_defaults={}, execution_data_source="ib")
            session.add(settings_row)
            session.commit()
            session.refresh(settings_row)
        return TradeSettingsOut.model_validate(settings_row, from_attributes=True)


@router.post("/settings", response_model=TradeSettingsOut)
def update_trade_settings(payload: TradeSettingsUpdate):
    with get_session() as session:
        settings_row = session.query(TradeSettings).order_by(TradeSettings.id.desc()).first()
        if settings_row is None:
            settings_row = TradeSettings(
                risk_defaults=payload.risk_defaults or {},
                execution_data_source="ib",
            )
            session.add(settings_row)
        else:
            settings_row.risk_defaults = payload.risk_defaults
            settings_row.execution_data_source = "ib"
        session.commit()
        session.refresh(settings_row)
        return TradeSettingsOut.model_validate(settings_row, from_attributes=True)


@router.get("/guard", response_model=TradeGuardStateOut)
def get_trade_guard_state(project_id: int, mode: str = "paper"):
    with get_session() as session:
        state = get_or_create_guard_state(session, project_id=project_id, mode=mode)
        return TradeGuardStateOut.model_validate(state, from_attributes=True)


@router.post("/guard/evaluate", response_model=TradeGuardEvaluateOut)
def evaluate_trade_guard(payload: TradeGuardEvaluateRequest):
    with get_session() as session:
        result = evaluate_intraday_guard(
            session,
            project_id=payload.project_id,
            mode=payload.mode,
            risk_params=payload.risk_params,
        )
        state = (
            session.query(TradeGuardState)
            .filter(
                TradeGuardState.project_id == payload.project_id,
                TradeGuardState.mode == payload.mode,
            )
            .order_by(TradeGuardState.id.desc())
            .first()
        )
        if state is None:
            raise HTTPException(status_code=404, detail="guard state not found")
        return TradeGuardEvaluateOut(
            state=TradeGuardStateOut.model_validate(state, from_attributes=True),
            result=result,
        )


def _build_market_symbols(orders: list[TradeOrderCreate]) -> list[str]:
    symbols = []
    for order in orders:
        symbol = str(order.symbol or "").strip().upper()
        if symbol:
            symbols.append(symbol)
    return sorted(set(symbols))


@router.get("/runs", response_model=list[TradeRunOut])
def list_trade_runs(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)):
    with get_session() as session:
        runs = (
            session.query(TradeRun)
            .order_by(TradeRun.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [TradeRunOut.model_validate(run, from_attributes=True) for run in runs]


@router.get("/runs/{run_id}", response_model=TradeRunOut)
def get_trade_run(run_id: int):
    with get_session() as session:
        run = session.get(TradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return TradeRunOut.model_validate(run, from_attributes=True)


@router.post("/runs", response_model=TradeRunOut)
def create_trade_run(payload: TradeRunCreate):
    with get_session() as session:
        params = payload.model_dump(exclude={"orders"})
        run = TradeRun(
            project_id=payload.project_id,
            decision_snapshot_id=payload.decision_snapshot_id,
            mode=payload.mode,
            status="queued",
            params=params,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        orders = payload.orders or []
        if not orders:
            run.status = "failed"
            run.message = "orders_empty"
            run.ended_at = datetime.utcnow()
            session.commit()
            out = TradeRunOut.model_validate(run, from_attributes=True)
            out.orders_created = 0
            return out

        if payload.require_market_health:
            symbols = _build_market_symbols(orders)
            health = check_market_health(
                session,
                symbols=symbols,
                min_success_ratio=payload.health_min_success_ratio,
                fallback_history=payload.health_fallback_history,
                history_duration=payload.health_history_duration,
                history_bar_size=payload.health_history_bar_size,
                history_use_rth=payload.health_history_use_rth,
            )
            params["market_health"] = health
            run.params = params
            if health.get("status") != "ok":
                run.status = "blocked"
                run.message = "market_health_blocked"
                run.ended_at = datetime.utcnow()
                session.commit()
                out = TradeRunOut.model_validate(run, from_attributes=True)
                out.orders_created = 0
                return out

        created = 0
        for order in orders:
            try:
                result = create_trade_order(session, order.model_dump(), run_id=run.id)
                if result.created:
                    created += 1
            except ValueError as exc:
                run.status = "failed"
                run.message = str(exc)
                run.ended_at = datetime.utcnow()
                session.commit()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        run.status = "queued"
        run.updated_at = datetime.utcnow()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            run.status = "failed"
            run.message = "client_order_id_conflict"
            run.ended_at = datetime.utcnow()
            session.commit()
            raise HTTPException(status_code=409, detail="client_order_id_conflict")
        record_audit(
            session,
            action="trade_run.create",
            resource_type="trade_run",
            resource_id=run.id,
            detail={"orders_created": created},
        )
        session.commit()
        out = TradeRunOut.model_validate(run, from_attributes=True)
        out.orders_created = created
        return out


@router.post("/runs/{run_id}/execute", response_model=TradeRunExecuteOut)
def execute_trade_run_route(run_id: int, payload: TradeRunExecuteRequest):
    try:
        result = execute_trade_run(run_id, dry_run=payload.dry_run, force=payload.force)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with get_session() as session:
        record_audit(
            session,
            action="trade_run.execute",
            resource_type="trade_run",
            resource_id=run_id,
            detail={
                "status": result.status,
                "filled": result.filled,
                "cancelled": result.cancelled,
                "rejected": result.rejected,
                "skipped": result.skipped,
                "dry_run": result.dry_run,
            },
        )
        session.commit()
    return TradeRunExecuteOut(**result.__dict__)


@router.get("/orders", response_model=list[TradeOrderOut])
def list_trade_orders(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    run_id: int | None = None,
):
    with get_session() as session:
        query = session.query(TradeOrder).order_by(TradeOrder.created_at.desc())
        if run_id is not None:
            query = query.filter(TradeOrder.run_id == run_id)
        orders = query.offset(offset).limit(limit).all()
        return [TradeOrderOut.model_validate(order, from_attributes=True) for order in orders]


@router.get("/orders/{order_id}", response_model=TradeOrderOut)
def get_trade_order(order_id: int):
    with get_session() as session:
        order = session.get(TradeOrder, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        return TradeOrderOut.model_validate(order, from_attributes=True)


@router.post("/orders", response_model=TradeOrderOut)
def create_trade_order_route(payload: TradeOrderCreate):
    with get_session() as session:
        try:
            result = create_trade_order(session, payload.model_dump())
            session.commit()
            session.refresh(result.order)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="client_order_id_conflict") from exc
        return TradeOrderOut.model_validate(result.order, from_attributes=True)


@router.post("/orders/{order_id}/status", response_model=TradeOrderOut)
def update_trade_order_status_route(order_id: int, payload: TradeOrderStatusUpdate):
    with get_session() as session:
        order = session.get(TradeOrder, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        try:
            order = update_trade_order_status(session, order, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return TradeOrderOut.model_validate(order, from_attributes=True)
