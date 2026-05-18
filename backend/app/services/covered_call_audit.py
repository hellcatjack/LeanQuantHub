from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.covered_call_timeline import build_covered_call_timeline
from app.services.trade_option_models import CoveredCallAuditRequest, CoveredCallTimelineRequest

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


def _build_artifact_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_audit_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(str(path))
    if not candidate.exists():
        return None
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def build_covered_call_audit(session, payload: CoveredCallAuditRequest) -> dict[str, Any]:
    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    review_id = str(getattr(payload, "review_id", "") or "").strip()
    if mode != "paper":
        raise ValueError("paper_only")
    if not review_id:
        raise ValueError("review_id_required")

    timeline = build_covered_call_timeline(
        session,
        CoveredCallTimelineRequest(mode=mode, review_id=review_id),
    )
    artifacts = dict(timeline.get("artifacts") or {})
    review_payload = _read_json(artifacts.get("review_bundle"))
    submit_payload = _read_json(artifacts.get("latest_submit_summary"))
    receipt_payload = _read_json(artifacts.get("latest_receipt_summary"))

    artifact_dir = _build_artifact_dir()
    summary_payload = {
        "mode": mode,
        "status": timeline.get("status"),
        "timeline_state": timeline.get("timeline_state"),
        "review_id": review_id,
        "review": review_payload,
        "submit": submit_payload,
        "receipt": receipt_payload,
        "timeline": timeline,
        "artifacts": {
            "review_bundle": artifacts.get("review_bundle"),
            "timeline_summary": artifacts.get("summary"),
            "latest_submit_summary": artifacts.get("latest_submit_summary"),
            "latest_receipt_summary": artifacts.get("latest_receipt_summary"),
        },
    }
    summary_path = _write_json(artifact_dir / "summary.json", summary_payload)

    return {
        "mode": mode,
        "status": timeline.get("status"),
        "timeline_state": timeline.get("timeline_state"),
        "review_id": review_id,
        "review": review_payload,
        "submit": submit_payload,
        "receipt": receipt_payload,
        "timeline": timeline,
        "artifacts": {
            "summary": summary_path,
            "review_bundle": artifacts.get("review_bundle"),
            "timeline_summary": artifacts.get("summary"),
            "latest_submit_summary": artifacts.get("latest_submit_summary"),
            "latest_receipt_summary": artifacts.get("latest_receipt_summary"),
        },
    }
