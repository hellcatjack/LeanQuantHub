from __future__ import annotations

from fastapi import APIRouter

from app.db import get_session
from app.models import BacktestSettings
from app.schemas import BacktestSettingsOut, BacktestSettingsUpdate


router = APIRouter(prefix="/api/backtest", tags=["backtests"])


def _get_or_create_settings(session) -> BacktestSettings:
    settings_row = session.query(BacktestSettings).order_by(BacktestSettings.id.desc()).first()
    if settings_row:
        return settings_row
    settings_row = BacktestSettings(
        default_initial_cash=30000,
        default_fee_bps=10.0,
    )
    session.add(settings_row)
    session.commit()
    session.refresh(settings_row)
    return settings_row


@router.get("/settings", response_model=BacktestSettingsOut)
def get_backtest_settings():
    with get_session() as session:
        settings_row = _get_or_create_settings(session)
        return BacktestSettingsOut.model_validate(settings_row, from_attributes=True)


@router.post("/settings", response_model=BacktestSettingsOut)
def update_backtest_settings(payload: BacktestSettingsUpdate):
    with get_session() as session:
        settings_row = _get_or_create_settings(session)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            if value is None:
                continue
            setattr(settings_row, key, value)
        session.commit()
        session.refresh(settings_row)
        return BacktestSettingsOut.model_validate(settings_row, from_attributes=True)
