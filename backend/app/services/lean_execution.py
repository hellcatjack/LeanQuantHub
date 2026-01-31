from __future__ import annotations

import json
from datetime import datetime, timezone
import subprocess
import os
from pathlib import Path

from app.core.config import settings
from app.db import SessionLocal
from app.models import TradeFill, TradeOrder, TradeRun
from app.services.ib_settings import derive_client_id
from app.services.trade_orders import create_trade_order, update_trade_order_status

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


def build_execution_config(
    *,
    intent_path: str,
    brokerage: str,
    project_id: int,
    mode: str,
    client_id: int | None = None,
    lean_bridge_output_dir: str | None = None,
) -> dict:
    payload = dict(_load_template_config())
    payload["environment"] = _resolve_environment(brokerage, mode)
    payload["algorithm-type-name"] = "LeanBridgeExecutionAlgorithm"
    if payload.get("algorithm-type-name") in {"LeanBridgeExecutionAlgorithm", "LeanBridgeSmokeAlgorithm"}:
        payload["algorithm-language"] = "CSharp"
    payload.setdefault("data-folder", "/data/share/stock/data/lean")
    payload["brokerage"] = brokerage
    payload["execution-intent-path"] = intent_path
    payload["result-handler"] = "QuantConnect.Lean.Engine.Results.LeanBridgeResultHandler"
    output_dir = lean_bridge_output_dir or _bridge_output_dir()
    payload["lean-bridge-output-dir"] = output_dir
    payload["lean-bridge-watchlist-path"] = str(Path(output_dir) / "watchlist.json")
    payload["lean-bridge-watchlist-refresh-seconds"] = "5"
    _write_watchlist_from_intent(intent_path, payload["lean-bridge-watchlist-path"])
    payload["ib-client-id"] = int(client_id) if client_id is not None else derive_client_id(
        project_id=project_id, mode=mode
    )
    return payload


def _write_watchlist_from_intent(intent_path: str, watchlist_path: str) -> None:
    intent_file = Path(intent_path)
    if not intent_file.exists():
        return

    try:
        items = json.loads(intent_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(items, list):
        return

    symbols: list[str] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)

    if not symbols:
        return

    watchlist_file = Path(watchlist_path)
    watchlist_file.parent.mkdir(parents=True, exist_ok=True)
    watchlist_file.write_text(json.dumps(symbols, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _build_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    if settings.dotnet_root:
        env["DOTNET_ROOT"] = settings.dotnet_root
        env["PATH"] = f"{settings.dotnet_root}:{env.get('PATH', '')}"
    if settings.python_dll:
        env["PYTHONNET_PYDLL"] = settings.python_dll
    if settings.lean_python_venv:
        env["PYTHONHOME"] = settings.lean_python_venv
    return env


def launch_execution(*, config_path: str) -> None:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    subprocess_run(cmd, check=False, cwd=cwd, env=_build_launch_env())

def launch_execution_async(*, config_path: str) -> int:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    proc = subprocess.Popen(cmd, cwd=cwd, env=_build_launch_env())
    return int(proc.pid)


def ingest_execution_events(path: str, *, session=None) -> dict:
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
    return apply_execution_events(events, session=session)


def _parse_event_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _apply_fill_to_order(
    session,
    order: TradeOrder,
    *,
    fill_qty: float,
    fill_price: float,
    fill_time: datetime,
    exec_id: str | None = None,
) -> TradeFill:
    current_status = str(order.status or "").strip().upper()
    total_prev = float(order.filled_quantity or 0.0)
    total_new = total_prev + float(fill_qty)
    avg_prev = float(order.avg_fill_price or 0.0)
    avg_new = (avg_prev * total_prev + float(fill_price) * float(fill_qty)) / total_new
    target_status = "PARTIAL" if total_new < float(order.quantity) else "FILLED"
    if current_status == "NEW":
        update_trade_order_status(session, order, {"status": "SUBMITTED"})
    update_trade_order_status(
        session,
        order,
        {"status": target_status, "filled_quantity": total_new, "avg_fill_price": avg_new},
    )
    if not exec_id:
        exec_id = f"lean:{order.id}:{int(fill_time.timestamp() * 1000)}"
    fill = TradeFill(
        order_id=order.id,
        exec_id=exec_id,
        fill_quantity=float(fill_qty),
        fill_price=float(fill_price),
        commission=None,
        fill_time=fill_time,
        params={"source": "lean_bridge"},
    )
    session.add(fill)
    session.commit()
    session.refresh(order)
    return fill


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


def apply_execution_events(events: list[dict], *, session=None) -> dict:
    own_session = False
    summary = {"processed": 0, "skipped_invalid_tag": 0, "skipped_not_found": 0}
    if session is None:
        session = SessionLocal()
        own_session = True
    try:
        for event in events or []:
            tag = str(event.get("tag") or "").strip()
            if not tag or not tag.startswith("oi_"):
                summary["skipped_invalid_tag"] += 1
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
                    summary["skipped_not_found"] += 1
                    continue
                symbol = (event.get("symbol") or intent.get("symbol") or "").strip().upper()
                if not symbol:
                    summary["skipped_not_found"] += 1
                    continue
                direction = str(event.get("direction") or "").strip().upper()
                side = "BUY" if direction in {"BUY", "LONG"} else "SELL" if direction in {"SELL", "SHORT"} else ""
                if not side:
                    summary["skipped_not_found"] += 1
                    continue
                filled_qty = float(event.get("filled") or 0.0)
                quantity = abs(filled_qty) if filled_qty else float(intent.get("quantity") or 0.0)
                if quantity <= 0:
                    summary["skipped_not_found"] += 1
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
                summary["processed"] += 1
                continue
            if status == "FILLED":
                filled_qty = float(event.get("filled") or 0.0)
                if filled_qty <= 0:
                    summary["skipped_not_found"] += 1
                    continue
                fill_price = float(event.get("fill_price") or 0.0)
                fill_time = _parse_event_time(event.get("time"))
                _apply_fill_to_order(
                    session,
                    order,
                    fill_qty=filled_qty,
                    fill_price=fill_price,
                    fill_time=fill_time,
                )
                summary["processed"] += 1
    finally:
        if own_session:
            session.close()
    return summary
