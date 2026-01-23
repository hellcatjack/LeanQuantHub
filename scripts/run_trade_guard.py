from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.trade_guard import evaluate_intraday_guard  # noqa: E402


def _run_once() -> None:
    session = SessionLocal()
    try:
        projects = session.query(Project).all()
        for project in projects:
            for mode in ("paper", "live"):
                evaluate_intraday_guard(session, project_id=project.id, mode=mode)
    finally:
        session.close()


if __name__ == "__main__":
    while True:
        _run_once()
        time.sleep(60)
