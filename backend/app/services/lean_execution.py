from __future__ import annotations

import json
import inspect
import subprocess
from pathlib import Path

from app.core.config import settings
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
    payload["lean-bridge-output-dir"] = lean_bridge_output_dir or _bridge_output_dir()
    payload["ib-client-id"] = client_id if client_id is not None else derive_client_id(project_id=project_id, mode=mode)
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
    kwargs: dict[str, object] = {"check": False}
    if cwd:
        try:
            sig = inspect.signature(subprocess_run)
        except (TypeError, ValueError):
            kwargs["cwd"] = cwd
        else:
            if "cwd" in sig.parameters or any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
            ):
                kwargs["cwd"] = cwd
    subprocess_run(cmd, **kwargs)


def launch_execution_async(*, config_path: str) -> int:
    dll_path, cwd = _resolve_launcher()
    cmd = [settings.dotnet_path or "dotnet", dll_path, "--config", config_path]
    kwargs: dict[str, object] = {}
    if cwd:
        try:
            sig = inspect.signature(subprocess.Popen)
        except (TypeError, ValueError):
            kwargs["cwd"] = cwd
        else:
            if "cwd" in sig.parameters or any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
            ):
                kwargs["cwd"] = cwd
    process = subprocess.Popen(cmd, **kwargs)
    return process.pid


def ingest_execution_events(path: str) -> None:
    events = json.loads(Path(path).read_text(encoding="utf-8"))
    apply_execution_events(events)


def apply_execution_events(events: list[dict]) -> None:
    # TODO: update trade_orders / trade_fills in DB
    return None
