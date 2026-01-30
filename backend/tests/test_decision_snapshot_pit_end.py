import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import decision_snapshot


def test_build_decision_configs_uses_pit_rebalance_end(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    pit_dir = data_root / "universe" / "pit_weekly"
    pit_dir.mkdir(parents=True)
    pit_path = pit_dir / "pit_20260123.csv"
    pit_path.write_text(
        "symbol,snapshot_date,rebalance_date\n"
        "AAPL,2026-01-23,2026-01-26\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(decision_snapshot, "_resolve_data_root", lambda: data_root)

    config = {"weights": {"A": 1.0}}
    output_dir = tmp_path / "out"
    theme_path, weights_path = decision_snapshot._build_decision_configs(
        1,
        config,
        None,
        "2026-01-23",
        {},
        output_dir,
    )
    assert theme_path.exists()
    assert weights_path.exists()
    weights_cfg = json.loads(weights_path.read_text(encoding="utf-8"))
    assert weights_cfg["backtest_start"] == "2026-01-23"
    assert weights_cfg["backtest_end"] == "2026-01-26"
