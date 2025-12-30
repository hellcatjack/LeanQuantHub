from __future__ import annotations

import math

from fastapi import APIRouter, Query

from app.db import get_session
from app.models import AuditLog
from app.schemas import AuditLogOut, AuditLogPageOut

router = APIRouter(prefix="/api/audit-logs", tags=["audit_logs"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
):
    with get_session() as session:
        query = session.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            query = query.filter(AuditLog.resource_id == resource_id)
        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/page", response_model=AuditLogPageOut)
def list_audit_logs_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
):
    with get_session() as session:
        query = session.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            query = query.filter(AuditLog.resource_id == resource_id)
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return AuditLogPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )
