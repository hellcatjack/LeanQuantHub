from pathlib import Path
import sys
import datetime as dt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import pit_runner


def _arg_value(cmd: list[str], key: str) -> str | None:
    if key not in cmd:
        return None
    idx = cmd.index(key)
    if idx + 1 >= len(cmd):
        return None
    return cmd[idx + 1]


def test_build_weekly_command_infers_end_when_missing(monkeypatch):
    monkeypatch.setattr(pit_runner, "_resolve_latest_trading_day_end", lambda _p: "2026-02-17")
    cmd = pit_runner._build_command({}, None)
    assert _arg_value(cmd, "--end") == "2026-02-17"


def test_build_weekly_command_keeps_explicit_end(monkeypatch):
    monkeypatch.setattr(pit_runner, "_resolve_latest_trading_day_end", lambda _p: "2026-02-17")
    cmd = pit_runner._build_command({"end": "2026-02-10"}, None)
    assert _arg_value(cmd, "--end") == "2026-02-10"


def test_build_fundamental_command_infers_end_when_missing(monkeypatch):
    monkeypatch.setattr(pit_runner, "_resolve_latest_trading_day_end", lambda _p: "2026-02-17")
    cmd = pit_runner._build_fundamental_command({}, None)
    assert _arg_value(cmd, "--end") == "2026-02-17"


def test_resolve_latest_trading_day_end_uses_latest_non_future(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    (data_root / "curated_adjusted").mkdir(parents=True, exist_ok=True)

    def _fake_load_days(_data_root, _adjusted_dir, _benchmark, _vendor_preference, source_override=None):
        _ = source_override
        return [dt.date(2026, 2, 10), dt.date(2026, 2, 17), dt.date(2026, 2, 24)], {}

    class FixedDateTime(dt.datetime):
        @classmethod
        def utcnow(cls):
            return dt.datetime(2026, 2, 17, 12, 0, 0)

    monkeypatch.setattr(pit_runner.trading_calendar, "load_trading_days", _fake_load_days)
    monkeypatch.setattr(pit_runner, "datetime", FixedDateTime)

    params = {"data_root": str(data_root), "benchmark": "SPY", "vendor_preference": "Alpha"}
    assert pit_runner._resolve_latest_trading_day_end(params) == "2026-02-17"
