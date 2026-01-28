from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import TradeOrder
from app.services.ib_orders import apply_fill_to_order
from app.services.ib_settings import derive_client_id
from app.services.trade_orders import update_trade_order_status

subprocess_run = subprocess.run

_DEFAULT_LAUNCHER_DIR = Path("/app/stocklean/Lean_git/Launcher/bin/Release")
_DEFAULT_CONFIG_TEMPLATE = Path("/app/stocklean/configs/lean_live_interactive_paper.json")


def _bridge_output_dir() -> str:
    base = settings.data_root or "/data/share/stock/data"
    return str(Path(base) / "lean_bridge")


def _resolve_template_path() -> Path | None:
    if settings.lean_config_template:
        path = Path(settings.lean_config_template)
        if path.exists():
            return path
    if _DEFAULT_CONFIG_TEMPLATE.exists():
        return _DEFAULT_CONFIG_TEMPLATE
    return None


def _load_template_config() -> dict:
    base: dict = {}
    path = _resolve_template_path()
    if path:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            base.update(payload)

    if _DEFAULT_CONFIG_TEMPLATE.exists():
        try:
            fallback = json.loads(_DEFAULT_CONFIG_TEMPLATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            fallback = {}
        if isinstance(fallback, dict):
            for key, value in fallback.items():
                if key not in base:
                    base[key] = value
                    continue
                existing = base.get(key)
                if existing in (None, "", [], {}):
                    base[key] = value

    return base


def _resolve_environment(brokerage: str, mode: str) -> str:
    if str(brokerage or "").lower() == "interactivebrokersbrokerage":
        return "live-interactive"
    return "live"


def build_execution_config(*, intent_path: str, brokerage: str, project_id: int, mode: str) -> dict:
    payload = dict(_load_template_config())
    payload["environment"] = _resolve_environment(brokerage, mode)
    payload["algorithm-type-name"] = "LeanBridgeExecutionAlgorithm"
    if payload.get("algorithm-type-name") in {"LeanBridgeExecutionAlgorithm", "LeanBridgeSmokeAlgorithm"}:
        payload["algorithm-language"] = "CSharp"
    payload.setdefault("data-folder", "/data/share/stock/data/lean")
    payload["brokerage"] = brokerage
    payload["execution-intent-path"] = intent_path
    payload["result-handler"] = "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    payload["lean-bridge-output-dir"] = _bridge_output_dir()
    payload["ib-client-id"] = derive_client_id(project_id=project_id, mode=mode)
    return payload


def _resolve_launcher() -> tuple[str, str | None]:
    dll_setting = str(settings.lean_launcher_dll or "").strip()
    launcher_path = str(settings.lean_launcher_path or "").strip()

    launcher_dir: Path | None = None
    if launcher_path:
        launcher_candidate = Path(launcher_path)
        if launcher_candidate.exists() and launcher_candidate.is_file():
            launcher_dir = launcher_candidate.parent
        else:
            launcher_dir = launcher_candidate

    if dll_setting:
        dll_path = Path(dll_setting)
        if not dll_path.is_absolute() and launcher_dir is not None:
            dll_path = launcher_dir / dll_path
        cwd = str(dll_path.parent) if dll_path.is_absolute() else (str(launcher_dir) if launcher_dir is not None else None)
        return str(dll_path), cwd

    if launcher_dir is not None:
        dll_path = launcher_dir / "QuantConnect.Lean.Launcher.dll"
        if not dll_path.exists():
            candidate = launcher_dir / "bin" / "Release" / "QuantConnect.Lean.Launcher.dll"
            if candidate.exists():
                return str(candidate), str(candidate.parent)
        return str(dll_path), str(launcher_dir)

    dll_path = _DEFAULT_LAUNCHER_DIR / "QuantConnect.Lean.Launcher.dll"
    return str(dll_path), str(_DEFAULT_LAUNCHER_DIR)


def launch_execution(*, config_path: str) -> None:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    subprocess_run(cmd, check=False, cwd=cwd)


def ingest_execution_events(path: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    cleaned = text.strip()
    if not cleaned:
        apply_execution_events([])
        return
    if cleaned.startswith("["):
        events = json.loads(cleaned)
        if isinstance(events, dict):
            events = [events]
        apply_execution_events(events)
        return
    events: list[dict] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    apply_execution_events(events)


def apply_execution_events(events: list[dict]) -> None:
    if not events:
        return None

    def _normalize_status(value: str | None) -> str:
        return str(value or "").strip().upper()

    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        cleaned = str(value).strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1]
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None

    session = SessionLocal()
    try:
        for event in events:
            if not isinstance(event, dict):
                continue
            tag = str(event.get("tag") or "").strip()
            if not tag:
                continue
            order = (
                session.query(TradeOrder)
                .filter(TradeOrder.client_order_id == tag)
                .one_or_none()
            )
            if not order:
                continue
            status = _normalize_status(event.get("status"))
            event_time = _parse_time(event.get("time"))
            if event_time and order.last_status_ts and event_time <= order.last_status_ts:
                continue
            if event.get("order_id") is not None and order.ib_order_id is None:
                try:
                    order.ib_order_id = int(event.get("order_id"))
                except (TypeError, ValueError):
                    pass
            if event.get("perm_id") is not None and order.ib_perm_id is None:
                try:
                    order.ib_perm_id = int(event.get("perm_id"))
                except (TypeError, ValueError):
                    pass

            if status in {"SUBMITTED", "NEW"}:
                update_trade_order_status(session, order, {"status": "SUBMITTED"})
            elif status in {"FILLED", "PARTIAL"}:
                fill_qty = float(event.get("filled") or 0.0)
                fill_price = float(event.get("fill_price") or 0.0)
                if fill_qty > 0 and fill_price > 0:
                    apply_fill_to_order(
                        session,
                        order,
                        fill_qty=fill_qty,
                        fill_price=fill_price,
                        fill_time=event_time or datetime.utcnow(),
                        exec_id=str(event.get("exec_id") or "") or None,
                    )
                else:
                    update_trade_order_status(
                        session,
                        order,
                        {"status": "FILLED" if status == "FILLED" else "PARTIAL"},
                    )
            elif status in {"CANCELED", "CANCELLED"}:
                update_trade_order_status(session, order, {"status": "CANCELED"})
            elif status == "REJECTED":
                update_trade_order_status(session, order, {"status": "REJECTED"})
            if event_time:
                order.last_status_ts = event_time
            session.commit()
    finally:
        session.close()
    return None
