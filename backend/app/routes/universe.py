from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.config import settings
from app.db import get_session
from app.models import UniverseMembership
from app.schemas import (
    UniverseExcludeItem,
    UniverseExcludeListOut,
    UniverseExcludePatchIn,
    UniverseExcludeUpsertIn,
    UniverseThemeListOut,
    UniverseThemeOut,
    UniverseThemeSymbolsOut,
)
from app.services import universe_exclude

router = APIRouter(prefix="/api/universe", tags=["universe"])

CSV_ENCODING = "utf-8-sig"
UNIVERSE_SOURCE = "universe_csv"


def _get_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.environ.get("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("C:/work/stocks/data")


def _read_universe_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _normalize_row_value(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ensure_universe_memberships(session) -> datetime | None:
    data_root = _get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    if not universe_path.exists():
        return None

    file_mtime = datetime.utcfromtimestamp(universe_path.stat().st_mtime)
    last_update = (
        session.query(func.max(UniverseMembership.source_updated_at)).scalar()
    )
    if last_update and last_update >= file_mtime:
        return last_update

    rows = _read_universe_csv(universe_path)
    session.query(UniverseMembership).delete()
    items: list[UniverseMembership] = []
    for row in rows:
        symbol = _normalize_row_value(row.get("symbol")).upper()
        category = _normalize_row_value(row.get("category"))
        if not symbol or not category:
            continue
        in_sp500_history = _normalize_row_value(row.get("in_sp500_history")) == "1"
        items.append(
            UniverseMembership(
                symbol=symbol,
                category=category,
                category_label=_normalize_row_value(row.get("category_label")) or None,
                region=_normalize_row_value(row.get("region")) or None,
                asset_class=_normalize_row_value(row.get("asset_class")) or None,
                in_sp500_history=in_sp500_history,
                start_date=_normalize_row_value(row.get("start_date")) or None,
                end_date=_normalize_row_value(row.get("end_date")) or None,
                source=_normalize_row_value(row.get("source")) or None,
                theme_source=_normalize_row_value(row.get("theme_source")) or None,
                theme_keyword=_normalize_row_value(row.get("theme_keyword")) or None,
                source_updated_at=file_mtime,
            )
        )
    if items:
        session.bulk_save_objects(items)
    session.commit()
    return file_mtime


@router.get("/themes", response_model=UniverseThemeListOut)
def list_universe_themes() -> UniverseThemeListOut:
    with get_session() as session:
        updated_at = _ensure_universe_memberships(session)
        rows = (
            session.query(
                UniverseMembership.category,
                func.max(UniverseMembership.category_label),
                func.count(UniverseMembership.id),
                func.max(UniverseMembership.source_updated_at),
            )
            .group_by(UniverseMembership.category)
            .order_by(UniverseMembership.category.asc())
            .all()
        )

        items = [
            UniverseThemeOut(
                key=category,
                label=label or category,
                symbols=count,
                updated_at=row_updated_at,
            )
            for category, label, count, row_updated_at in rows
        ]

        return UniverseThemeListOut(items=items, updated_at=updated_at)


@router.get("/themes/{category}/symbols", response_model=UniverseThemeSymbolsOut)
def list_universe_theme_symbols(category: str) -> UniverseThemeSymbolsOut:
    normalized = category.strip()
    with get_session() as session:
        updated_at = _ensure_universe_memberships(session)
        label = (
            session.query(func.max(UniverseMembership.category_label))
            .filter(UniverseMembership.category == normalized)
            .scalar()
        )
        row_updated_at = (
            session.query(func.max(UniverseMembership.source_updated_at))
            .filter(UniverseMembership.category == normalized)
            .scalar()
        )
        symbols = [
            row[0]
            for row in (
                session.query(UniverseMembership.symbol)
                .filter(UniverseMembership.category == normalized)
                .distinct()
                .order_by(UniverseMembership.symbol.asc())
                .all()
            )
        ]

    return UniverseThemeSymbolsOut(
        key=normalized,
        label=label,
        symbols=symbols,
        updated_at=row_updated_at or updated_at,
    )


@router.get("/excludes", response_model=UniverseExcludeListOut)
def list_universe_excludes(enabled: bool | None = None) -> UniverseExcludeListOut:
    include_disabled = enabled is None or enabled is False
    items = universe_exclude.load_exclude_items(
        None, include_disabled=include_disabled
    )
    if enabled is True:
        items = [row for row in items if row.get("enabled") != "false"]
    out_items = [
        UniverseExcludeItem(
            symbol=row.get("symbol", ""),
            enabled=row.get("enabled") != "false",
            reason=row.get("reason") or "",
            source=row.get("source") or "",
            created_at=row.get("created_at") or None,
            updated_at=row.get("updated_at") or None,
        )
        for row in items
    ]
    return UniverseExcludeListOut(items=out_items)


@router.post("/excludes", response_model=UniverseExcludeItem)
def create_universe_exclude(payload: UniverseExcludeUpsertIn) -> UniverseExcludeItem:
    symbol = (payload.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol_invalid")
    universe_exclude.upsert_exclude_item(
        None,
        symbol=symbol,
        reason=payload.reason or "",
        source=payload.source or "manual/ui",
        enabled=payload.enabled is not False,
    )
    items = universe_exclude.load_exclude_items(None, include_disabled=True)
    row = next(item for item in items if item["symbol"] == symbol)
    return UniverseExcludeItem(
        symbol=row["symbol"],
        enabled=row.get("enabled") != "false",
        reason=row.get("reason") or "",
        source=row.get("source") or "",
        created_at=row.get("created_at") or None,
        updated_at=row.get("updated_at") or None,
    )


@router.patch("/excludes/{symbol}", response_model=UniverseExcludeItem)
def patch_universe_exclude(
    symbol: str, payload: UniverseExcludePatchIn
) -> UniverseExcludeItem:
    normalized = (symbol or "").strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="symbol_invalid")
    universe_exclude.upsert_exclude_item(
        None,
        symbol=normalized,
        reason=payload.reason or "",
        source=payload.source or "manual/ui",
        enabled=payload.enabled is not False,
    )
    items = universe_exclude.load_exclude_items(None, include_disabled=True)
    row = next(item for item in items if item["symbol"] == normalized)
    return UniverseExcludeItem(
        symbol=row["symbol"],
        enabled=row.get("enabled") != "false",
        reason=row.get("reason") or "",
        source=row.get("source") or "",
        created_at=row.get("created_at") or None,
        updated_at=row.get("updated_at") or None,
    )
