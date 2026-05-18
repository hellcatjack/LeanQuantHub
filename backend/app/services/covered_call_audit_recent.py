from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.covered_call_timeline import build_covered_call_timeline
from app.services.trade_option_models import CoveredCallAuditRecentRequest, CoveredCallTimelineRequest

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _to_iso_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_symbol(review_bundle: dict[str, Any] | None) -> str | None:
    if not isinstance(review_bundle, dict):
        return None
    order_plan = review_bundle.get("order_plan")
    if isinstance(order_plan, dict):
        symbol = str(order_plan.get("underlying_symbol") or "").strip().upper()
        if symbol:
            return symbol
    eligible = review_bundle.get("eligible")
    if isinstance(eligible, dict):
        symbol = str(eligible.get("symbol") or "").strip().upper()
        if symbol:
            return symbol
    return None


def _matches_query(review_id: str, symbol: str | None, status: str, timeline_state: str, query: str) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    haystacks = [
        review_id.lower(),
        str(symbol or "").strip().lower(),
        status.lower(),
        timeline_state.lower(),
    ]
    return any(needle in item for item in haystacks if item)


def list_covered_call_audit_recent(session, payload: CoveredCallAuditRecentRequest) -> dict[str, Any]:
    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    limit = max(1, min(50, int(getattr(payload, "limit", 10) or 10)))
    offset = max(0, int(getattr(payload, "offset", 0) or 0))
    query = str(getattr(payload, "query", "") or "")
    if mode != "paper":
        raise ValueError("paper_only")

    bundles: list[Path] = []
    for review_dir in ARTIFACT_ROOT.glob("options_review_*"):
        if not review_dir.is_dir():
            continue
        bundle_path = review_dir / "review_bundle.json"
        if not bundle_path.exists():
            continue
        bundles.append(bundle_path)
    bundles.sort(key=lambda item: item.stat().st_mtime, reverse=True)

    filtered_items: list[dict[str, Any]] = []
    for bundle_path in bundles:
        review_bundle = _read_json(bundle_path)
        if not isinstance(review_bundle, dict):
            continue
        review_id = str(review_bundle.get("review_id") or bundle_path.parent.name).strip()
        if not review_id:
            continue
        try:
            timeline = build_covered_call_timeline(
                session,
                CoveredCallTimelineRequest(mode=mode, review_id=review_id),
            )
        except ValueError:
            continue
        latest_submit = timeline.get("latest_submit")
        symbol = _extract_symbol(review_bundle)
        status = str(timeline.get("status") or "unknown")
        timeline_state = str(timeline.get("timeline_state") or "unknown")
        if not _matches_query(review_id, symbol, status, timeline_state, query):
            continue
        filtered_items.append(
            {
                "review_id": review_id,
                "created_at": _to_iso_from_mtime(bundle_path),
                "symbol": symbol,
                "status": status,
                "timeline_state": timeline_state,
                "latest_command_id": str((latest_submit or {}).get("command_id") or "").strip() or None,
            }
        )

    total = len(filtered_items)
    items = filtered_items[offset : offset + limit]

    return {
        "mode": mode,
        "total": total,
        "has_more": offset + len(items) < total,
        "items": items,
    }
