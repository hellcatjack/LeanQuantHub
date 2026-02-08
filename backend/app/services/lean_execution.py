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
    params_path: str | None = None,
    lean_bridge_output_dir: str | None = None,
) -> dict:
    payload = dict(_load_template_config())
    payload["environment"] = _resolve_environment(brokerage, mode)
    payload["algorithm-type-name"] = "LeanBridgeExecutionAlgorithm"
    # Prevent Lean console launcher from blocking on "Press any key to continue." after completion.
    payload["close-automatically"] = True
    if payload.get("algorithm-type-name") in {"LeanBridgeExecutionAlgorithm", "LeanBridgeSmokeAlgorithm"}:
        payload["algorithm-language"] = "CSharp"
    payload.setdefault("data-folder", "/data/share/stock/data/lean")
    payload["brokerage"] = brokerage
    payload["execution-intent-path"] = intent_path
    if params_path:
        payload["execution-params-path"] = params_path
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
        # A single-line jsonl file is valid JSON (dict). Treat it as one event.
        if isinstance(parsed, list):
            events = parsed
        elif isinstance(parsed, dict):
            events = [parsed]
        else:
            events = []
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
    if session is None:
        return apply_execution_events(events)
    return apply_execution_events(events, session=session)


def _parse_event_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        tz = ""
        tz_index = None
        for sep in ("+", "-"):
            idx = tail.find(sep)
            if idx > 0:
                tz_index = idx
                break
        if tz_index is not None:
            frac = tail[:tz_index]
            tz = tail[tz_index:]
        else:
            frac = tail
        if len(frac) > 6:
            frac = frac[:6]
        text = f"{head}.{frac}{tz}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _apply_fill_to_order(
    session,
    order: TradeOrder,
    *,
    fill_qty: float,
    fill_price: float,
    fill_time: datetime,
    exec_id: str | None = None,
) -> TradeFill:
    if not exec_id:
        exec_id = f"lean:{order.id}:{int(fill_time.timestamp() * 1000)}"
    existing = (
        session.query(TradeFill)
        .filter(TradeFill.order_id == order.id, TradeFill.exec_id == exec_id)
        .first()
    )
    if existing:
        return existing
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


def _parse_intent_run_id(intent_id: str) -> int | None:
    if not intent_id:
        return None
    parts = str(intent_id).split("_")
    if len(parts) < 3 or parts[0] != "oi":
        return None
    try:
        return int(parts[1])
    except (TypeError, ValueError):
        return None


def _find_intent_for_id(session, intent_id: str) -> tuple[TradeRun | None, dict | None]:
    if not intent_id:
        return None, None
    run_id = _parse_intent_run_id(intent_id)
    if run_id:
        run = session.get(TradeRun, run_id)
        if run is not None:
            params = run.params or {}
            intent_path = params.get("order_intent_path")
            if intent_path:
                for item in _load_intent_items(intent_path):
                    if str(item.get("order_intent_id") or "").strip() == intent_id:
                        return run, item
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


def _merge_duplicate_order(session, *, target: TradeOrder, duplicate: TradeOrder) -> None:
    fills = session.query(TradeFill).filter(TradeFill.order_id == duplicate.id).all()
    for fill in fills:
        fill.order_id = target.id
    session.delete(duplicate)
    session.commit()
    session.refresh(target)


def apply_execution_events(events: list[dict], *, session=None) -> dict:
    own_session = False
    summary = {"processed": 0, "skipped_invalid_tag": 0, "skipped_not_found": 0}
    if session is None:
        session = SessionLocal()
        own_session = True
    try:
        for event in events or []:
            tag = str(event.get("tag") or "").strip()
            if not tag:
                summary["skipped_invalid_tag"] += 1
                continue

            status = str(event.get("status") or "").strip().upper()
            filled_value = float(event.get("filled") or 0.0)
            event_time_iso = str(event.get("time") or "").strip()
            event_params = {
                "event_source": "lean",
                "event_tag": tag,
                "event_time": event_time_iso,
                "event_status": status,
            }

            # Direct order events use tag `direct:{trade_order_id}` and are stored under
            # `lean_bridge/direct_{trade_order_id}/execution_events.jsonl`.
            if tag.startswith("direct:"):
                raw = tag[len("direct:") :].strip()
                try:
                    order_id = int(raw)
                except ValueError:
                    summary["skipped_invalid_tag"] += 1
                    continue
                order = session.get(TradeOrder, order_id)
                if order is None:
                    summary["skipped_not_found"] += 1
                    continue

                lean_order_id = event.get("order_id")
                if lean_order_id is not None and order.ib_order_id is None:
                    try:
                        order.ib_order_id = int(lean_order_id)
                        session.commit()
                        session.refresh(order)
                    except (TypeError, ValueError):
                        pass

                if status in {"SUBMITTED", "NEW"}:
                    current_status = str(order.status or "").strip().upper()
                    if current_status in {"NEW", "SUBMITTED"}:
                        try:
                            update_trade_order_status(
                                session, order, {"status": "SUBMITTED", "params": event_params}
                            )
                        except ValueError:
                            continue
                    summary["processed"] += 1
                    continue

                if status in {"CANCELED", "CANCELLED"}:
                    current_status = str(order.status or "").strip().upper()
                    if current_status not in {"CANCELED", "CANCELLED", "REJECTED", "FILLED"}:
                        try:
                            update_trade_order_status(
                                session, order, {"status": "CANCELED", "params": event_params}
                            )
                        except ValueError:
                            continue
                    summary["processed"] += 1
                    continue

                if status in {"REJECTED", "INVALID"}:
                    if str(order.status or "").strip().upper() != "REJECTED":
                        update_payload = {"status": "REJECTED", "params": dict(event_params)}
                        reason = event.get("reason") or event.get("message")
                        if reason:
                            update_payload["params"]["reason"] = str(reason)
                        try:
                            update_trade_order_status(session, order, update_payload)
                        except ValueError:
                            continue
                    summary["processed"] += 1
                    continue

                if status in {"FILLED", "PARTIALLYFILLED", "PARTIAL"} or filled_value > 0:
                    if filled_value <= 0:
                        summary["skipped_not_found"] += 1
                        continue
                    fill_price = float(event.get("fill_price") or 0.0)
                    fill_time = _parse_event_time(event.get("time"))
                    exec_id = event.get("exec_id") or f"lean_direct:{order.id}:{int(fill_time.timestamp() * 1000)}"
                    try:
                        _apply_fill_to_order(
                            session,
                            order,
                            fill_qty=filled_value,
                            fill_price=fill_price,
                            fill_time=fill_time,
                            exec_id=exec_id,
                        )
                        # Preserve event metadata on the order for UI/debugging.
                        try:
                            update_trade_order_status(
                                session, order, {"status": str(order.status or "FILLED"), "params": event_params}
                            )
                        except ValueError:
                            pass
                    except ValueError:
                        continue
                    summary["processed"] += 1
                    continue

                summary["skipped_invalid_tag"] += 1
                continue

            if not tag.startswith("oi_"):
                summary["skipped_invalid_tag"] += 1
                continue

            intent_id = tag
            run_id_hint = _parse_intent_run_id(intent_id)
            duplicate_order = None
            order = (
                session.query(TradeOrder)
                .filter(TradeOrder.client_order_id == intent_id)
                .one_or_none()
            )
            if order is not None and run_id_hint and order.run_id != run_id_hint:
                duplicate_order = order
                order = None
            if order is None:
                run, intent = _find_intent_for_id(session, intent_id)
                if run is None:
                    if duplicate_order is not None:
                        order = duplicate_order
                    else:
                        summary["skipped_not_found"] += 1
                        continue
                if run is not None:
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
                    existing_orders = (
                        session.query(TradeOrder)
                        .filter(
                            TradeOrder.run_id == run.id,
                            TradeOrder.symbol == symbol,
                            TradeOrder.side == side,
                        )
                        .all()
                    )
                    matched = None
                    if existing_orders:
                        if quantity > 0:
                            for candidate in existing_orders:
                                if abs(float(candidate.quantity) - float(quantity)) < 1e-6:
                                    matched = candidate
                                    break
                        # For SUBMITTED events, filled quantity is 0 and intent drafts may omit quantity.
                        # In that case, fall back to symbol+side match when it is unambiguous.
                        if matched is None and len(existing_orders) == 1:
                            matched = existing_orders[0]
                    if matched is not None:
                        order = matched
                    else:
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
                    if duplicate_order is not None and order.id != duplicate_order.id:
                        _merge_duplicate_order(session, target=order, duplicate=duplicate_order)
            order_id = event.get("order_id")
            if order_id is not None and order.ib_order_id is None:
                order.ib_order_id = int(order_id)
                session.commit()
                session.refresh(order)
            current_status = str(order.status or "").strip().upper()

            if status in {"SUBMITTED", "NEW"}:
                if current_status in {"NEW", "SUBMITTED"}:
                    try:
                        update_trade_order_status(
                            session, order, {"status": "SUBMITTED", "params": event_params}
                        )
                    except ValueError:
                        continue
                summary["processed"] += 1
                continue

            if status in {"CANCELED", "CANCELLED"}:
                if current_status not in {"CANCELED", "CANCELLED", "REJECTED", "FILLED"}:
                    try:
                        update_trade_order_status(
                            session, order, {"status": "CANCELED", "params": event_params}
                        )
                    except ValueError:
                        continue
                summary["processed"] += 1
                continue

            if status in {"REJECTED", "INVALID"}:
                if current_status != "REJECTED":
                    update_payload = {"status": "REJECTED", "params": dict(event_params)}
                    reason = event.get("reason") or event.get("message")
                    if reason:
                        update_payload["params"]["reason"] = str(reason)
                    try:
                        update_trade_order_status(session, order, update_payload)
                    except ValueError:
                        continue
                summary["processed"] += 1
                continue

            if status in {"FILLED", "PARTIALLYFILLED", "PARTIAL"} or filled_value > 0:
                filled_qty = float(event.get("filled") or 0.0)
                if filled_qty <= 0:
                    summary["skipped_not_found"] += 1
                    continue
                fill_price = float(event.get("fill_price") or 0.0)
                fill_time = _parse_event_time(event.get("time"))
                exec_id = event.get("exec_id") or f"lean:{order.id}:{int(fill_time.timestamp() * 1000)}"
                try:
                    _apply_fill_to_order(
                        session,
                        order,
                        fill_qty=filled_qty,
                        fill_price=fill_price,
                        fill_time=fill_time,
                        exec_id=exec_id,
                    )
                    # Preserve event metadata on the order for UI/debugging.
                    try:
                        update_trade_order_status(
                            session, order, {"status": str(order.status or "FILLED"), "params": event_params}
                        )
                    except ValueError:
                        pass
                except ValueError:
                    continue
                summary["processed"] += 1
                continue

            summary["skipped_invalid_tag"] += 1
    finally:
        if own_session:
            session.close()
    return summary
