from pathlib import Path
import json

from app.services.trade_order_intent import write_order_intent, ensure_order_intent_ids


def test_write_order_intent_adds_ids(tmp_path: Path) -> None:
    items = [
        {"symbol": "AAA", "weight": 0.1, "snapshot_date": "2026-01-30", "rebalance_date": "2026-02-03"},
        {"symbol": "BBB", "weight": 0.2, "snapshot_date": "2026-01-30", "rebalance_date": "2026-02-03"},
    ]
    path = write_order_intent(None, snapshot_id=46, items=items, output_dir=tmp_path)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert len(payload) == 2
    for entry in payload:
        assert entry.get("order_intent_id")


def test_write_order_intent_uses_run_id_prefix(tmp_path: Path) -> None:
    items = [
        {"symbol": "AAPL", "weight": 0.1, "snapshot_date": "2026-01-16", "rebalance_date": "2026-01-16"},
    ]
    path = write_order_intent(None, snapshot_id=46, items=items, output_dir=tmp_path, run_id=7)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload[0]["order_intent_id"].startswith("oi_7_")


def test_write_order_intent_writes_prime_price_map(tmp_path: Path) -> None:
    items = [
        {"symbol": "AAPL", "weight": 0.1, "snapshot_date": "2026-01-16", "rebalance_date": "2026-01-16"},
    ]
    path = write_order_intent(
        None,
        snapshot_id=46,
        items=items,
        output_dir=tmp_path,
        run_id=7,
        order_type="ADAPTIVE_LMT",
        prime_price_map={"AAPL": 189.25},
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload[0]["prime_price"] == 189.25
    assert payload[0].get("limit_price") is None


def test_ensure_order_intent_ids_rewrites_missing(tmp_path: Path) -> None:
    path = tmp_path / "intent.json"
    payload = [
        {"symbol": "AAA", "weight": 0.1},
        {"symbol": "BBB", "weight": 0.2, "order_intent_id": "existing"},
        {"symbol": "", "weight": 0.3},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    updated = ensure_order_intent_ids(str(path), snapshot_id=46)
    assert updated is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0].get("order_intent_id")
    assert data[1].get("order_intent_id") == "existing"
    assert data[2].get("order_intent_id")
