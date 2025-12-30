from __future__ import annotations

from datetime import datetime

from app.models import AuditLog


def record_audit(
    session,
    *,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    actor: str = "system",
    detail: dict | None = None,
) -> None:
    entry = AuditLog(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        created_at=datetime.utcnow(),
    )
    session.add(entry)
