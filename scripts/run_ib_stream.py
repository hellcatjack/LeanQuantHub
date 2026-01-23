from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services import ib_stream  # noqa: E402


def _refresh_interval(config: dict) -> int:
    raw = config.get("refresh_interval_seconds")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 30
    return max(5, value)


if __name__ == "__main__":
    stream_root = ib_stream._resolve_stream_root(None)
    try:
        with ib_stream.stream_lock(stream_root.parent):
            while True:
                config = ib_stream.read_stream_config(stream_root)
                if not config:
                    ib_stream.write_stream_status(
                        stream_root,
                        status="disconnected",
                        symbols=[],
                        market_data_type="delayed",
                    )
                    time.sleep(10)
                    continue
                market_data_type = config.get("market_data_type") or "delayed"
                symbols = config.get("symbols") or []
                ib_stream.write_stream_status(
                    stream_root,
                    status="connected",
                    symbols=symbols,
                    market_data_type=market_data_type,
                )
                time.sleep(_refresh_interval(config))
    except RuntimeError:
        ib_stream.write_stream_status(
            stream_root,
            status="disconnected",
            symbols=[],
            market_data_type="delayed",
            error="ib_stream_lock_busy",
        )
