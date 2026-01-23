from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.services import ib_stream  # noqa: E402


if __name__ == "__main__":
    stream_root = ib_stream._resolve_stream_root(None)
    try:
        with ib_stream.stream_lock(stream_root.parent):
            runner = ib_stream.IBStreamRunner(project_id=0, data_root=stream_root.parent, api_mode="ib")
            runner.run_forever()
    except RuntimeError as exc:
        ib_stream.handle_stream_lock_error(stream_root, exc)
