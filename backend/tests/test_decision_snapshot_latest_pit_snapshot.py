from pathlib import Path
import sys

import datetime as dt

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import decision_snapshot


def test_resolve_latest_pit_snapshot_ignores_future_dates(tmp_path, monkeypatch):
    pit_dir = tmp_path / "universe" / "pit_weekly"
    pit_dir.mkdir(parents=True)
    (pit_dir / "pit_20260206.csv").write_text("", encoding="utf-8")
    (pit_dir / "pit_20270122.csv").write_text("", encoding="utf-8")

    class FixedDateTime(dt.datetime):
        @classmethod
        def utcnow(cls):
            return dt.datetime(2026, 2, 6, 12, 0, 0)

    monkeypatch.setattr(decision_snapshot, "_resolve_data_root", lambda: tmp_path)
    monkeypatch.setattr(decision_snapshot, "datetime", FixedDateTime)

    assert decision_snapshot._resolve_latest_pit_snapshot() == "2026-02-06"


def test_resolve_latest_pit_snapshot_returns_none_when_only_future(tmp_path, monkeypatch):
    pit_dir = tmp_path / "universe" / "pit_weekly"
    pit_dir.mkdir(parents=True)
    (pit_dir / "pit_20270122.csv").write_text("", encoding="utf-8")

    class FixedDateTime(dt.datetime):
        @classmethod
        def utcnow(cls):
            return dt.datetime(2026, 2, 6, 12, 0, 0)

    monkeypatch.setattr(decision_snapshot, "_resolve_data_root", lambda: tmp_path)
    monkeypatch.setattr(decision_snapshot, "datetime", FixedDateTime)

    assert decision_snapshot._resolve_latest_pit_snapshot() is None

