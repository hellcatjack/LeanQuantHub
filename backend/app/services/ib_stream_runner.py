from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class StreamSnapshotWriter:
    def __init__(self, stream_root: Path) -> None:
        self.stream_root = stream_root
        self.stream_root.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, symbol: str, payload: dict) -> None:
        symbol = str(symbol or "").strip().upper()
        path = self.stream_root / f"{symbol}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class StreamStatusWriter:
    def __init__(self, stream_root: Path) -> None:
        self.stream_root = stream_root
        self.stream_root.mkdir(parents=True, exist_ok=True)

    def write_status(
        self,
        *,
        status: str,
        symbols: list[str],
        error: str | None,
        market_data_type: str,
    ) -> None:
        payload = {
            "status": status,
            "last_heartbeat": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "subscribed_symbols": sorted({str(sym or "").strip().upper() for sym in symbols}),
            "ib_error_count": 0 if not error else 1,
            "last_error": error,
            "market_data_type": market_data_type,
        }
        (self.stream_root / "_status.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
