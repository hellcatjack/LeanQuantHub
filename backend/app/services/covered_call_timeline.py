from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.trade_option_models import CoveredCallTimelineRequest

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


def _build_artifact_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_timeline_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _load_review_bundle(review_id: str) -> tuple[Path, dict[str, Any]]:
    bundle_path = ARTIFACT_ROOT / review_id / "review_bundle.json"
    if not bundle_path.exists():
        raise ValueError("review_not_found")
    payload = _read_json(bundle_path)
    if not isinstance(payload, dict):
        raise ValueError("review_bundle_invalid")
    return bundle_path, payload


def _find_latest_summary(
    prefix: str,
    *,
    review_id: str,
    command_id: str | None = None,
) -> tuple[Path | None, dict[str, Any] | None]:
    latest_path: Path | None = None
    latest_payload: dict[str, Any] | None = None
    for summary_path in sorted(ARTIFACT_ROOT.glob(f"{prefix}_*/summary.json")):
        try:
            payload = _read_json(summary_path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("review_id") or "").strip() != review_id:
            continue
        if command_id is not None and str(payload.get("command_id") or "").strip() != command_id:
            continue
        latest_path = summary_path
        latest_payload = payload
    return latest_path, latest_payload


def _build_stages(*, review_bundle: dict[str, Any], latest_submit: dict[str, Any] | None, latest_receipt: dict[str, Any] | None) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = [
        {
            "stage": "review",
            "status": str(review_bundle.get("status") or "unknown"),
            "gate_reason": review_bundle.get("gate_reason"),
        }
    ]
    if latest_submit is not None:
        stages.append(
            {
                "stage": "submit",
                "status": str(latest_submit.get("status") or "unknown"),
                "gate_reason": latest_submit.get("gate_reason"),
                "command_id": latest_submit.get("command_id"),
                "command_result_status": latest_submit.get("command_result_status"),
            }
        )
    if latest_receipt is not None:
        stages.append(
            {
                "stage": "receipt",
                "status": str(latest_receipt.get("status") or "unknown"),
                "receipt_state": latest_receipt.get("receipt_state"),
                "gate_reason": latest_receipt.get("gate_reason"),
                "command_id": latest_receipt.get("command_id"),
                "command_result_status": latest_receipt.get("command_result_status"),
            }
        )
    return stages


def _resolve_timeline_state(*, review_bundle: dict[str, Any], latest_submit: dict[str, Any] | None, latest_receipt: dict[str, Any] | None) -> tuple[str, str]:
    review_status = str(review_bundle.get("status") or "unknown")
    if review_status == "blocked":
        return "blocked", "review_blocked"
    if latest_receipt is not None:
        receipt_status = str(latest_receipt.get("status") or "unknown")
        receipt_state = str(latest_receipt.get("receipt_state") or "unknown")
        if receipt_status == "rejected":
            return "rejected", receipt_state or "rejected"
        return receipt_status, receipt_state or "receipt_recorded"
    if latest_submit is not None:
        submit_status = str(latest_submit.get("status") or "unknown")
        if submit_status == "blocked":
            return "blocked", "submit_blocked"
        if submit_status == "submitted":
            return "submitted", "submit_submitted"
        return submit_status, f"submit_{submit_status}"
    return review_status, f"review_{review_status}"


def build_covered_call_timeline(session, payload: CoveredCallTimelineRequest) -> dict[str, Any]:
    del session

    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    review_id = str(getattr(payload, "review_id", "") or "").strip()
    if mode != "paper":
        raise ValueError("paper_only")
    if not review_id:
        raise ValueError("review_id_required")

    review_bundle_path, review_bundle = _load_review_bundle(review_id)
    submit_summary_path, latest_submit = _find_latest_summary("options_submit", review_id=review_id)
    latest_submit_command_id = (
        str((latest_submit or {}).get("command_id") or "").strip() or None
    )
    receipt_summary_path = None
    latest_receipt = None
    if latest_submit_command_id:
        receipt_summary_path, latest_receipt = _find_latest_summary(
            "options_receipt",
            review_id=review_id,
            command_id=latest_submit_command_id,
        )

    status, timeline_state = _resolve_timeline_state(
        review_bundle=review_bundle,
        latest_submit=latest_submit,
        latest_receipt=latest_receipt,
    )
    stages = _build_stages(
        review_bundle=review_bundle,
        latest_submit=latest_submit,
        latest_receipt=latest_receipt,
    )

    artifact_dir = _build_artifact_dir()
    summary_payload = {
        "mode": mode,
        "status": status,
        "timeline_state": timeline_state,
        "review_id": review_id,
        "latest_submit": latest_submit,
        "latest_receipt": latest_receipt,
        "stages": stages,
        "review_bundle": str(review_bundle_path),
        "latest_submit_summary": str(submit_summary_path) if submit_summary_path else None,
        "latest_receipt_summary": str(receipt_summary_path) if receipt_summary_path else None,
    }
    summary_path = _write_json(artifact_dir / "summary.json", summary_payload)

    return {
        "mode": mode,
        "status": status,
        "timeline_state": timeline_state,
        "review_id": review_id,
        "latest_submit": latest_submit,
        "latest_receipt": latest_receipt,
        "stages": stages,
        "artifacts": {
            "summary": summary_path,
            "review_bundle": str(review_bundle_path),
            "latest_submit_summary": str(submit_summary_path) if submit_summary_path else None,
            "latest_receipt_summary": str(receipt_summary_path) if receipt_summary_path else None,
        },
    }
