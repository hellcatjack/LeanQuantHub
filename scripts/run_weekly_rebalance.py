from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.pretrade_runner import create_pretrade_run_for_project, run_pretrade_run  # noqa: E402


if __name__ == "__main__":
    session = SessionLocal()
    try:
        projects = session.query(Project).all()
        for project in projects:
            run = create_pretrade_run_for_project(session, project_id=project.id)
            run_pretrade_run(run.id)
    finally:
        session.close()
