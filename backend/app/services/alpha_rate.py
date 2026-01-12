from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


DEFAULT_MAX_RPM = 154
DEFAULT_MIN_DELAY_SECONDS = 0.12
DEFAULT_RATE_LIMIT_SLEEP = 10.0
DEFAULT_RATE_LIMIT_RETRIES = 3
DEFAULT_MAX_RETRIES = 3
DEFAULT_AUTO_TUNE = True
DEFAULT_MIN_DELAY_FLOOR_SECONDS = 0.1
DEFAULT_MIN_DELAY_CEIL_SECONDS = 2.0
DEFAULT_TUNE_STEP_SECONDS = 0.02
DEFAULT_TUNE_WINDOW_SECONDS = 60.0
DEFAULT_TUNE_TARGET_RATIO_LOW = 0.9
DEFAULT_TUNE_TARGET_RATIO_HIGH = 1.05
DEFAULT_TUNE_COOLDOWN_SECONDS = 10.0
DEFAULT_TUNE_SUSPEND_SECONDS = 60.0
DEFAULT_RATE_LIMIT_STEP_SECONDS = 0.1
DEFAULT_RPM_FLOOR = 90.0
DEFAULT_RPM_CEIL = 170.0
DEFAULT_RPM_STEP_DOWN = 5.0
DEFAULT_RPM_STEP_UP = 2.0

_last_rate_limit_event_at: float | None = None
_alpha_request_times: deque[float] = deque()
_alpha_last_rate_limit_at: float | None = None
_alpha_last_tune_at: float = 0.0
_alpha_tune_suspend_until: float = time.monotonic() + DEFAULT_TUNE_SUSPEND_SECONDS


def _resolve_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.getenv("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("/data/share/stock/data")


def alpha_rate_config_path(data_root: Path | None = None) -> Path:
    root = data_root or _resolve_data_root()
    return root / "config" / "alpha_rate.json"


def _coerce_float(value: Any, default: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if num > 0 else default


def _coerce_int(value: Any, default: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return num if num > 0 else default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _defaults() -> dict[str, Any]:
    max_rpm = _coerce_float(getattr(settings, "alpha_max_rpm", None), DEFAULT_MAX_RPM)
    min_delay = _coerce_float(
        getattr(settings, "alpha_min_delay_seconds", None), DEFAULT_MIN_DELAY_SECONDS
    )
    return {
        "max_rpm": max_rpm,
        "rpm_floor": DEFAULT_RPM_FLOOR,
        "rpm_ceil": DEFAULT_RPM_CEIL,
        "rpm_step_down": DEFAULT_RPM_STEP_DOWN,
        "rpm_step_up": DEFAULT_RPM_STEP_UP,
        "min_delay_seconds": min_delay,
        "rate_limit_sleep": _coerce_float(
            getattr(settings, "alpha_rate_limit_sleep", None), DEFAULT_RATE_LIMIT_SLEEP
        ),
        "rate_limit_retries": _coerce_int(
            getattr(settings, "alpha_rate_limit_retries", None), DEFAULT_RATE_LIMIT_RETRIES
        ),
        "max_retries": _coerce_int(
            getattr(settings, "alpha_max_retries", None), DEFAULT_MAX_RETRIES
        ),
        "auto_tune": _coerce_bool(getattr(settings, "alpha_auto_tune", None), DEFAULT_AUTO_TUNE),
        "min_delay_floor_seconds": DEFAULT_MIN_DELAY_FLOOR_SECONDS,
        "min_delay_ceil_seconds": DEFAULT_MIN_DELAY_CEIL_SECONDS,
        "tune_step_seconds": DEFAULT_TUNE_STEP_SECONDS,
        "tune_window_seconds": DEFAULT_TUNE_WINDOW_SECONDS,
        "tune_target_ratio_low": DEFAULT_TUNE_TARGET_RATIO_LOW,
        "tune_target_ratio_high": DEFAULT_TUNE_TARGET_RATIO_HIGH,
        "tune_cooldown_seconds": DEFAULT_TUNE_COOLDOWN_SECONDS,
    }


def load_alpha_rate_config(data_root: Path | None = None) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = alpha_rate_config_path(root)
    config = _defaults()
    source = "default"
    updated_at = None
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                config["max_rpm"] = _coerce_float(payload.get("max_rpm"), config["max_rpm"])
                config["rpm_floor"] = _coerce_float(
                    payload.get("rpm_floor"), config.get("rpm_floor", DEFAULT_RPM_FLOOR)
                )
                config["rpm_ceil"] = _coerce_float(
                    payload.get("rpm_ceil"), config.get("rpm_ceil", config["max_rpm"])
                )
                config["rpm_step_down"] = _coerce_float(
                    payload.get("rpm_step_down"),
                    config.get("rpm_step_down", DEFAULT_RPM_STEP_DOWN),
                )
                config["rpm_step_up"] = _coerce_float(
                    payload.get("rpm_step_up"),
                    config.get("rpm_step_up", DEFAULT_RPM_STEP_UP),
                )
                config["min_delay_seconds"] = _coerce_float(
                    payload.get("min_delay_seconds"), config["min_delay_seconds"]
                )
                config["auto_tune"] = _coerce_bool(
                    payload.get("auto_tune"), config["auto_tune"]
                )
                config["min_delay_floor_seconds"] = _coerce_float(
                    payload.get("min_delay_floor_seconds"), config["min_delay_floor_seconds"]
                )
                config["min_delay_ceil_seconds"] = _coerce_float(
                    payload.get("min_delay_ceil_seconds"), config["min_delay_ceil_seconds"]
                )
                config["tune_step_seconds"] = _coerce_float(
                    payload.get("tune_step_seconds"), config["tune_step_seconds"]
                )
                config["tune_window_seconds"] = _coerce_float(
                    payload.get("tune_window_seconds"), config["tune_window_seconds"]
                )
                config["tune_target_ratio_low"] = _coerce_float(
                    payload.get("tune_target_ratio_low"), config["tune_target_ratio_low"]
                )
                config["tune_target_ratio_high"] = _coerce_float(
                    payload.get("tune_target_ratio_high"), config["tune_target_ratio_high"]
                )
                config["tune_cooldown_seconds"] = _coerce_float(
                    payload.get("tune_cooldown_seconds"), config["tune_cooldown_seconds"]
                )
                config["rate_limit_sleep"] = _coerce_float(
                    payload.get("rate_limit_sleep"), config["rate_limit_sleep"]
                )
                config["rate_limit_retries"] = _coerce_int(
                    payload.get("rate_limit_retries"), config["rate_limit_retries"]
                )
                config["max_retries"] = _coerce_int(
                    payload.get("max_retries"), config["max_retries"]
                )
                updated_at = payload.get("updated_at")
                source = "file"
        except (OSError, json.JSONDecodeError):
            source = "default"

    rpm_floor = _coerce_float(config.get("rpm_floor"), DEFAULT_RPM_FLOOR)
    rpm_ceil = _coerce_float(config.get("rpm_ceil"), config["max_rpm"])
    if rpm_ceil < rpm_floor:
        rpm_ceil = rpm_floor
    max_rpm = _coerce_float(config.get("max_rpm"), DEFAULT_MAX_RPM)
    max_rpm = min(max(max_rpm, rpm_floor), rpm_ceil)
    config["max_rpm"] = max_rpm
    config["rpm_floor"] = rpm_floor
    config["rpm_ceil"] = rpm_ceil

    min_delay_floor = _coerce_float(
        config.get("min_delay_floor_seconds"), DEFAULT_MIN_DELAY_FLOOR_SECONDS
    )
    min_delay_ceil = _coerce_float(
        config.get("min_delay_ceil_seconds"), DEFAULT_MIN_DELAY_CEIL_SECONDS
    )
    if min_delay_ceil < min_delay_floor:
        min_delay_ceil = min_delay_floor
    min_delay = _coerce_float(config.get("min_delay_seconds"), DEFAULT_MIN_DELAY_SECONDS)
    min_delay = min(max(min_delay, min_delay_floor), min_delay_ceil)
    config["min_delay_seconds"] = min_delay
    config["min_delay_floor_seconds"] = min_delay_floor
    config["min_delay_ceil_seconds"] = min_delay_ceil
    ratio_low = _coerce_float(
        config.get("tune_target_ratio_low"), DEFAULT_TUNE_TARGET_RATIO_LOW
    )
    ratio_high = _coerce_float(
        config.get("tune_target_ratio_high"), DEFAULT_TUNE_TARGET_RATIO_HIGH
    )
    if ratio_high < ratio_low:
        ratio_high = ratio_low
    config["tune_target_ratio_low"] = ratio_low
    config["tune_target_ratio_high"] = ratio_high

    derived = DEFAULT_MIN_DELAY_SECONDS
    if config["max_rpm"] > 0:
        derived = 60.0 / config["max_rpm"]
    effective_min_delay = max(min_delay, derived)
    config["effective_min_delay_seconds"] = effective_min_delay
    config["updated_at"] = updated_at
    config["source"] = source
    config["path"] = str(path)
    return config


def write_alpha_rate_config(
    updates: dict[str, Any], data_root: Path | None = None
) -> dict[str, Any]:
    root = data_root or _resolve_data_root()
    path = alpha_rate_config_path(root)
    current = load_alpha_rate_config(root)
    payload = {
        "max_rpm": current["max_rpm"],
        "rpm_floor": current.get("rpm_floor", DEFAULT_RPM_FLOOR),
        "rpm_ceil": current.get("rpm_ceil", current["max_rpm"]),
        "rpm_step_down": current.get("rpm_step_down", DEFAULT_RPM_STEP_DOWN),
        "rpm_step_up": current.get("rpm_step_up", DEFAULT_RPM_STEP_UP),
        "min_delay_seconds": current["min_delay_seconds"],
        "rate_limit_sleep": current["rate_limit_sleep"],
        "rate_limit_retries": current["rate_limit_retries"],
        "max_retries": current["max_retries"],
        "auto_tune": current.get("auto_tune", DEFAULT_AUTO_TUNE),
        "min_delay_floor_seconds": current.get(
            "min_delay_floor_seconds", DEFAULT_MIN_DELAY_FLOOR_SECONDS
        ),
        "min_delay_ceil_seconds": current.get(
            "min_delay_ceil_seconds", DEFAULT_MIN_DELAY_CEIL_SECONDS
        ),
        "tune_step_seconds": current.get("tune_step_seconds", DEFAULT_TUNE_STEP_SECONDS),
        "tune_window_seconds": current.get("tune_window_seconds", DEFAULT_TUNE_WINDOW_SECONDS),
        "tune_target_ratio_low": current.get(
            "tune_target_ratio_low", DEFAULT_TUNE_TARGET_RATIO_LOW
        ),
        "tune_target_ratio_high": current.get(
            "tune_target_ratio_high", DEFAULT_TUNE_TARGET_RATIO_HIGH
        ),
        "tune_cooldown_seconds": current.get(
            "tune_cooldown_seconds", DEFAULT_TUNE_COOLDOWN_SECONDS
        ),
    }
    for key in list(payload.keys()):
        if key in updates and updates[key] is not None:
            if key in {
                "max_rpm",
                "rpm_floor",
                "rpm_ceil",
                "rpm_step_down",
                "rpm_step_up",
                "min_delay_seconds",
                "rate_limit_sleep",
                "min_delay_floor_seconds",
                "min_delay_ceil_seconds",
                "tune_step_seconds",
                "tune_window_seconds",
                "tune_target_ratio_low",
                "tune_target_ratio_high",
                "tune_cooldown_seconds",
            }:
                payload[key] = _coerce_float(updates[key], payload[key])
            elif key == "auto_tune":
                payload[key] = _coerce_bool(updates[key], payload[key])
            else:
                payload[key] = _coerce_int(updates[key], payload[key])
    payload["updated_at"] = datetime.utcnow().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return load_alpha_rate_config(root)


def apply_alpha_rate_limit_penalty(data_root: Path | None = None) -> dict[str, Any]:
    config = load_alpha_rate_config(data_root)
    if not _coerce_bool(config.get("auto_tune"), DEFAULT_AUTO_TUNE):
        return config
    rate_limit_sleep = _coerce_float(
        config.get("rate_limit_sleep"), DEFAULT_RATE_LIMIT_SLEEP
    )
    now = time.monotonic()
    global _last_rate_limit_event_at
    if (
        _last_rate_limit_event_at is not None
        and now - _last_rate_limit_event_at < 2 * rate_limit_sleep
    ):
        _last_rate_limit_event_at = now
        return config
    _last_rate_limit_event_at = now
    step = _coerce_float(config.get("tune_step_seconds"), DEFAULT_TUNE_STEP_SECONDS)
    step = max(step, DEFAULT_RATE_LIMIT_STEP_SECONDS)
    min_delay_floor = _coerce_float(
        config.get("min_delay_floor_seconds"), DEFAULT_MIN_DELAY_FLOOR_SECONDS
    )
    min_delay_ceil = _coerce_float(
        config.get("min_delay_ceil_seconds"), DEFAULT_MIN_DELAY_CEIL_SECONDS
    )
    if min_delay_ceil < min_delay_floor:
        min_delay_ceil = min_delay_floor
    current_delay = _coerce_float(
        config.get("min_delay_seconds"), DEFAULT_MIN_DELAY_SECONDS
    )
    next_delay = min(max(current_delay + step, min_delay_floor), min_delay_ceil)

    step_down = _coerce_float(config.get("rpm_step_down"), DEFAULT_RPM_STEP_DOWN)
    floor = _coerce_float(config.get("rpm_floor"), DEFAULT_RPM_FLOOR)
    current = _coerce_float(config.get("max_rpm"), DEFAULT_MAX_RPM)
    next_rpm = current
    if step_down > 0 and current > floor:
        next_rpm = max(current - step_down, floor)

    delay_changed = abs(next_delay - current_delay) >= 1e-6
    rpm_changed = abs(next_rpm - current) >= 1e-6
    if not delay_changed and not rpm_changed:
        return config
    updates: dict[str, Any] = {}
    if delay_changed:
        updates["min_delay_seconds"] = next_delay
    if rpm_changed:
        updates["max_rpm"] = next_rpm
    return write_alpha_rate_config(updates, data_root)


def _trim_request_times(window: float, now: float) -> None:
    while _alpha_request_times and now - _alpha_request_times[0] > window:
        _alpha_request_times.popleft()


def _maybe_auto_tune_alpha_rate(
    config: dict[str, Any],
    rate_per_min: float,
    target_rpm: float,
    rate_limited_recent: bool,
    data_root: Path | None,
) -> dict[str, Any] | None:
    auto_tune = _coerce_bool(config.get("auto_tune"), DEFAULT_AUTO_TUNE)
    if not auto_tune or target_rpm <= 0:
        return None
    now = time.monotonic()
    cooldown = _coerce_float(
        config.get("tune_cooldown_seconds"), DEFAULT_TUNE_COOLDOWN_SECONDS
    )
    global _alpha_last_tune_at
    if cooldown > 0 and now - _alpha_last_tune_at < cooldown:
        return None
    step = _coerce_float(config.get("tune_step_seconds"), DEFAULT_TUNE_STEP_SECONDS)
    floor = _coerce_float(
        config.get("min_delay_floor_seconds"), DEFAULT_MIN_DELAY_FLOOR_SECONDS
    )
    ceil = _coerce_float(
        config.get("min_delay_ceil_seconds"), DEFAULT_MIN_DELAY_CEIL_SECONDS
    )
    if ceil < floor:
        ceil = floor
    ratio_low = _coerce_float(
        config.get("tune_target_ratio_low"), DEFAULT_TUNE_TARGET_RATIO_LOW
    )
    ratio_high = _coerce_float(
        config.get("tune_target_ratio_high"), DEFAULT_TUNE_TARGET_RATIO_HIGH
    )
    if ratio_high < ratio_low:
        ratio_high = ratio_low
    current = _coerce_float(config.get("min_delay_seconds"), DEFAULT_MIN_DELAY_SECONDS)
    effective = _coerce_float(config.get("effective_min_delay_seconds"), current)
    current_rpm = _coerce_float(config.get("max_rpm"), DEFAULT_MAX_RPM)
    rpm_floor = _coerce_float(config.get("rpm_floor"), DEFAULT_RPM_FLOOR)
    rpm_ceil = _coerce_float(config.get("rpm_ceil"), current_rpm or rpm_floor)
    rpm_step_down = _coerce_float(config.get("rpm_step_down"), DEFAULT_RPM_STEP_DOWN)
    rpm_step_up = _coerce_float(config.get("rpm_step_up"), DEFAULT_RPM_STEP_UP)

    ratio = rate_per_min / target_rpm if target_rpm > 0 else 0.0
    reason = ""
    rpm_reason = ""
    next_delay = current
    next_rpm = current_rpm

    if rate_limited_recent:
        reason = "rate_limited"
        next_delay = current + step
        if rpm_step_down > 0 and current_rpm > rpm_floor:
            rpm_reason = "rpm_down"
            next_rpm = max(current_rpm - rpm_step_down, rpm_floor)
    elif ratio < ratio_low:
        reason = "below_target"
        delay_gap = effective - current
        if delay_gap + 1e-6 >= step:
            if rpm_step_up > 0 and current_rpm < rpm_ceil:
                rpm_reason = "rpm_up"
                next_rpm = min(current_rpm + rpm_step_up, rpm_ceil)
        else:
            next_delay = current - step
    elif ratio > ratio_high:
        reason = "above_target"
        next_delay = current + step

    if not reason and not rpm_reason:
        return None
    next_delay = min(max(next_delay, floor), ceil)
    delay_changed = abs(next_delay - current) >= 1e-6
    rpm_changed = abs(next_rpm - current_rpm) >= 1e-6
    if not delay_changed and not rpm_changed:
        return None

    updates: dict[str, Any] = {}
    if delay_changed:
        updates["min_delay_seconds"] = next_delay
    if rpm_changed:
        updates["max_rpm"] = next_rpm
    result = write_alpha_rate_config(updates, data_root)
    _alpha_last_tune_at = now
    return result


def note_alpha_request(
    data_root: Path | None = None, rate_limited: bool = False
) -> dict[str, Any] | None:
    config = load_alpha_rate_config(data_root)
    now = time.monotonic()
    window = _coerce_float(config.get("tune_window_seconds"), DEFAULT_TUNE_WINDOW_SECONDS)
    if window <= 0:
        window = DEFAULT_TUNE_WINDOW_SECONDS
    _alpha_request_times.append(now)
    _trim_request_times(window, now)

    global _alpha_last_rate_limit_at, _alpha_tune_suspend_until
    if rate_limited:
        _alpha_last_rate_limit_at = now
        rate_limit_sleep = _coerce_float(
            config.get("rate_limit_sleep"), DEFAULT_RATE_LIMIT_SLEEP
        )
        _alpha_tune_suspend_until = max(
            _alpha_tune_suspend_until, now + rate_limit_sleep + DEFAULT_TUNE_SUSPEND_SECONDS
        )
        return apply_alpha_rate_limit_penalty(data_root)

    if now < _alpha_tune_suspend_until:
        return None

    rate_per_min = (len(_alpha_request_times) * 60.0 / window) if window > 0 else 0.0
    target_rpm = float(config.get("max_rpm") or 0.0) or 0.0
    rate_limited_recent = (
        _alpha_last_rate_limit_at is not None and (now - _alpha_last_rate_limit_at) <= window
    )
    return _maybe_auto_tune_alpha_rate(
        config, rate_per_min, target_rpm, rate_limited_recent, data_root
    )
