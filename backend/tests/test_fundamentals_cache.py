from __future__ import annotations

from datetime import date
from pathlib import Path
import json
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import pretrade_runner


FUNDAMENTALS_FILES = (
    "overview.json",
    "income_statement.json",
    "balance_sheet.json",
    "cash_flow.json",
)


def _write_cache_meta(path: Path, as_of: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"as_of": as_of}), encoding="utf-8")


def _write_status(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "symbol,status,updated_at,message\n"
    lines = [header]
    for row in rows:
        lines.append(
            f"{row['symbol']},{row['status']},{row['updated_at']},{row.get('message','')}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


def _touch(path: Path, iso_ts: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    ts = pretrade_runner.datetime.fromisoformat(iso_ts).timestamp()
    import os

    os.utime(path, (ts, ts))


def test_fundamentals_cache_fresh_when_last_friday_present(tmp_path):
    data_root = tmp_path / "data"
    meta_path = pretrade_runner._fundamentals_cache_meta_path(data_root)
    _write_cache_meta(meta_path, "2026-01-23")

    fresh, last_friday = pretrade_runner._fundamentals_cache_fresh(
        data_root, today=date(2026, 1, 27)
    )

    assert last_friday.isoformat() == "2026-01-23"
    assert fresh is True


def test_fundamentals_cache_not_fresh_when_older(tmp_path):
    data_root = tmp_path / "data"
    meta_path = pretrade_runner._fundamentals_cache_meta_path(data_root)
    _write_cache_meta(meta_path, "2026-01-16")

    fresh, last_friday = pretrade_runner._fundamentals_cache_fresh(
        data_root, today=date(2026, 1, 27)
    )

    assert last_friday.isoformat() == "2026-01-23"
    assert fresh is False


def test_fundamentals_symbol_fresh_requires_status_and_files(tmp_path):
    data_root = tmp_path / "data"
    status_path = data_root / "fundamentals" / "alpha" / "fundamentals_status.csv"
    _write_status(
        status_path,
        [{"symbol": "AAPL", "status": "ok", "updated_at": "2026-01-24T00:00:00"}],
    )
    symbol_dir = data_root / "fundamentals" / "alpha" / "AAPL"
    for filename in FUNDAMENTALS_FILES:
        _touch(symbol_dir / filename, "2026-01-24T01:00:00")

    fresh = pretrade_runner._fundamentals_symbol_fresh(
        data_root, "AAPL", pretrade_runner.date(2026, 1, 23)
    )

    assert fresh is True


def test_fundamentals_symbol_not_fresh_when_status_old(tmp_path):
    data_root = tmp_path / "data"
    status_path = data_root / "fundamentals" / "alpha" / "fundamentals_status.csv"
    _write_status(
        status_path,
        [{"symbol": "AAPL", "status": "ok", "updated_at": "2026-01-16T00:00:00"}],
    )
    symbol_dir = data_root / "fundamentals" / "alpha" / "AAPL"
    for filename in FUNDAMENTALS_FILES:
        _touch(symbol_dir / filename, "2026-01-24T01:00:00")

    fresh = pretrade_runner._fundamentals_symbol_fresh(
        data_root, "AAPL", pretrade_runner.date(2026, 1, 23)
    )

    assert fresh is False


def test_fundamentals_symbol_not_fresh_when_file_missing(tmp_path):
    data_root = tmp_path / "data"
    status_path = data_root / "fundamentals" / "alpha" / "fundamentals_status.csv"
    _write_status(
        status_path,
        [{"symbol": "AAPL", "status": "ok", "updated_at": "2026-01-24T00:00:00"}],
    )
    symbol_dir = data_root / "fundamentals" / "alpha" / "AAPL"
    for filename in FUNDAMENTALS_FILES[:-1]:
        _touch(symbol_dir / filename, "2026-01-24T01:00:00")

    fresh = pretrade_runner._fundamentals_symbol_fresh(
        data_root, "AAPL", pretrade_runner.date(2026, 1, 23)
    )

    assert fresh is False


def test_fundamentals_missing_symbols_only_includes_missing(tmp_path):
    data_root = tmp_path / "data"
    status_path = data_root / "fundamentals" / "alpha" / "fundamentals_status.csv"
    _write_status(
        status_path,
        [
            {"symbol": "AAPL", "status": "ok", "updated_at": "2026-01-24T00:00:00"},
            {"symbol": "MSFT", "status": "ok", "updated_at": "2026-01-24T00:00:00"},
        ],
    )
    aapl_dir = data_root / "fundamentals" / "alpha" / "AAPL"
    for filename in FUNDAMENTALS_FILES:
        _touch(aapl_dir / filename, "2026-01-24T01:00:00")
    msft_dir = data_root / "fundamentals" / "alpha" / "MSFT"
    for filename in FUNDAMENTALS_FILES[:-1]:
        _touch(msft_dir / filename, "2026-01-24T01:00:00")

    missing = pretrade_runner._fundamentals_missing_symbols(
        data_root, ["AAPL", "MSFT"], pretrade_runner.date(2026, 1, 23)
    )

    assert missing == ["MSFT"]
