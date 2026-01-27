from __future__ import annotations

import json
from datetime import datetime, timezone
import subprocess
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import TradeOrder, TradeRun
from app.services.ib_orders import apply_fill_to_order
from app.services.trade_orders import create_trade_order, update_trade_order_status
from app.services.ib_settings import derive_client_id

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
    content = Path(path).read_text(encoding="utf-8")
    try:
        parsed = json.loads(content)
        events = parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        events = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    apply_execution_events(events)


def _parse_event_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _load_intent_items(path: str) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _find_intent_for_id(session, intent_id: str) -> tuple[TradeRun | None, dict | None]:
    if not intent_id:
        return None, None
    runs = session.query(TradeRun).all()
    for run in runs:
        params = run.params or {}
        intent_path = params.get("order_intent_path")
        if not intent_path:
            continue
        for item in _load_intent_items(intent_path):
            if str(item.get("order_intent_id") or "").strip() == intent_id:
                return run, item
    return None, None


def apply_execution_events(events: list[dict], *, session=None) -> None:
    own_session = False
    if session is None:
        session = SessionLocal()
        own_session = True
    try:
        for event in events or []:
            tag = str(event.get("tag") or "").strip()
            if not tag:
                continue
            intent_id = tag
            order = (
                session.query(TradeOrder)
                .filter(TradeOrder.client_order_id == intent_id)
                .one_or_none()
            )
            if order is None:
                run, intent = _find_intent_for_id(session, intent_id)
                if run is None:
                    continue
                symbol = (event.get("symbol") or intent.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                direction = str(event.get("direction") or "").strip().upper()
                side = "BUY" if direction in {"BUY", "LONG"} else "SELL" if direction in {"SELL", "SHORT"} else ""
                if not side:
                    continue
                filled_qty = float(event.get("filled") or 0.0)
                quantity = abs(filled_qty) if filled_qty else float(intent.get("quantity") or 0.0)
                if quantity <= 0:
                    continue
                payload = {
                    "client_order_id": intent_id,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "order_type": "MKT",
                    "params": {"source": "lean_bridge"},
                }
                result = create_trade_order(session, payload, run_id=run.id)
                session.commit()
                order = result.order
            order_id = event.get("order_id")
            if order_id is not None and order.ib_order_id is None:
                order.ib_order_id = int(order_id)
                session.commit()
                session.refresh(order)
            status = str(event.get("status") or "").strip().upper()
            if status == "SUBMITTED":
                update_trade_order_status(session, order, {"status": "SUBMITTED"})
                continue
            if status == "FILLED":
                filled_qty = float(event.get("filled") or 0.0)
                if filled_qty <= 0:
                    continue
                fill_price = float(event.get("fill_price") or 0.0)
                fill_time = _parse_event_time(event.get("time"))
                apply_fill_to_order(
                    session,
                    order,
                    fill_qty=filled_qty,
                    fill_price=fill_price,
                    fill_time=fill_time,
                )
    finally:
        if own_session:
            session.close()
