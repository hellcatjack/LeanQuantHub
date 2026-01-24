from __future__ import annotations

import json
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
