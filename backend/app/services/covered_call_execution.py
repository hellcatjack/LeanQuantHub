from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.covered_call_pilot import run_covered_call_pilot
from app.services.trade_option_models import CoveredCallExecutionPrepareRequest, CoveredCallPilotRequest, OptionOrderPlan

ARTIFACT_ROOT = Path(settings.artifact_root) if settings.artifact_root else Path("/app/stocklean/artifacts")


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _build_artifact_dir() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = ARTIFACT_ROOT / f"options_execution_{timestamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _build_option_order_plan(eligible_row: dict[str, Any]) -> OptionOrderPlan:
    recommendation = dict(eligible_row.get("recommended") or {})
    contracts = int(recommendation.get("contracts") or eligible_row.get("coverable_contracts") or 0)
    return OptionOrderPlan(
        underlying_symbol=str(eligible_row.get("symbol") or recommendation.get("symbol") or ""),
        side="SELL",
        expiry=str(recommendation.get("expiry") or ""),
        strike=float(recommendation.get("strike") or 0.0),
        right=str(recommendation.get("right") or "C"),
        contracts=contracts,
        quantity=contracts,
        limit_price=float(recommendation.get("mid") or 0.0),
        risk_tags=list(recommendation.get("risk_tags") or []),
    )


def prepare_covered_call_execution(session, payload: CoveredCallExecutionPrepareRequest) -> dict[str, Any]:
    mode = str(getattr(payload, "mode", "paper") or "paper").strip().lower() or "paper"
    dry_run = bool(getattr(payload, "dry_run", True))
    if mode != "paper":
        raise ValueError("paper_only")
    if not dry_run:
        raise ValueError("dry_run_only")

    symbol = _normalize_symbol(getattr(payload, "symbol", ""))
    if not symbol:
        raise ValueError("symbol_required")

    pilot_result = run_covered_call_pilot(
        session,
        CoveredCallPilotRequest(
            mode=mode,
            symbols=[symbol],
            max_candidates_per_symbol=int(getattr(payload, "max_candidates_per_symbol", 5) or 5),
            dte_min=int(getattr(payload, "dte_min", 21) or 21),
            dte_max=int(getattr(payload, "dte_max", 45) or 45),
            max_spread_ratio=float(getattr(payload, "max_spread_ratio", 0.15) or 0.15),
            dry_run=True,
        ),
    )

    artifact_dir = _build_artifact_dir()
    eligible_items = pilot_result.get("eligible")
    if not isinstance(eligible_items, list):
        eligible_items = []
    rejected_items = pilot_result.get("rejected")
    if not isinstance(rejected_items, list):
        rejected_items = []

    selected = dict(eligible_items[0]) if eligible_items else None
    order_plan = _build_option_order_plan(selected) if selected else None
    risk_tags = list((order_plan.risk_tags if order_plan else []) or [])

    if selected is None:
        gate_reason = str((rejected_items[0] or {}).get("reason") or "no_eligible_underlying") if rejected_items else "no_eligible_underlying"
        status = "blocked"
    elif risk_tags:
        gate_reason = "risk_tags_present"
        status = "review_required"
    else:
        gate_reason = None
        status = "ready"

    summary_payload = {
        "mode": mode,
        "status": status,
        "gate_reason": gate_reason,
        "symbol": symbol,
        "eligible": selected,
        "order_plan": order_plan.model_dump() if order_plan else None,
        "pilot_artifacts": dict(pilot_result.get("artifacts") or {}),
    }
    summary_path = _write_json(artifact_dir / "summary.json", summary_payload)
    plan_path = None
    if order_plan is not None:
        plan_path = _write_json(artifact_dir / "execution_plan.json", order_plan.model_dump())

    return {
        "mode": mode,
        "status": status,
        "gate_reason": gate_reason,
        "eligible": selected,
        "order_plan": order_plan.model_dump() if order_plan else None,
        "artifacts": {
            "summary": summary_path,
            "plan": plan_path,
            "pilot_summary": str((pilot_result.get("artifacts") or {}).get("summary") or "") or None,
        },
    }
