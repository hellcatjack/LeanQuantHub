from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import SessionLocal
from app.models import FactorScoreJob


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_ml_python() -> str:
    if settings.ml_python_path:
        return settings.ml_python_path
    candidate = _project_root() / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return "python3"


def _resolve_path(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = _project_root() / path
    return str(path)


def _build_command(params: dict[str, Any], output_dir: Path) -> tuple[list[str], str | None]:
    script_path = _project_root() / "scripts" / "build_factor_scores.py"
    cmd = [_resolve_ml_python(), str(script_path)]

    data_root = str(params.get("data_root") or settings.data_root or "").strip()
    if data_root:
        cmd.extend(["--data-root", data_root])

    start = str(params.get("start") or "").strip()
    if start:
        cmd.extend(["--start", start])
    end = str(params.get("end") or "").strip()
    if end:
        cmd.extend(["--end", end])

    config_path = _resolve_path(params.get("config_path"))
    if config_path:
        cmd.extend(["--config", config_path])

    pit_weekly_dir = _resolve_path(params.get("pit_weekly_dir"))
    if pit_weekly_dir:
        cmd.extend(["--pit-weekly-dir", pit_weekly_dir])

    pit_fundamentals_dir = _resolve_path(params.get("pit_fundamentals_dir"))
    if pit_fundamentals_dir:
        cmd.extend(["--pit-fundamentals-dir", pit_fundamentals_dir])

    adjusted_dir = _resolve_path(params.get("adjusted_dir"))
    if adjusted_dir:
        cmd.extend(["--adjusted-dir", adjusted_dir])

    exclude_symbols = _resolve_path(params.get("exclude_symbols"))
    if exclude_symbols:
        cmd.extend(["--exclude-symbols", exclude_symbols])

    cache_dir = _resolve_path(params.get("cache_dir"))
    if cache_dir:
        cmd.extend(["--cache-dir", cache_dir])
    else:
        cmd.extend(["--cache-dir", str(output_dir / "cache")])

    output_path = _resolve_path(params.get("output_path"))
    if output_path:
        cmd.extend(["--output", output_path])
    else:
        output_path = str(_project_root() / "ml" / "models" / "factor_scores.csv")
        cmd.extend(["--output", output_path])

    if params.get("overwrite_cache"):
        cmd.append("--overwrite-cache")

    return cmd, output_path


def run_factor_score_job(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(FactorScoreJob, job_id)
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.utcnow()
        session.commit()

        output_dir = Path(settings.artifact_root) / f"factor_score_job_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "factor_scores.log"

        job.output_dir = str(output_dir)
        job.log_path = str(log_path)
        session.commit()

        params = dict(job.params or {})
        cmd, score_path = _build_command(params, output_dir)
        if score_path:
            job.scores_path = score_path
            session.commit()

        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"running: {' '.join(cmd)}\n")
            proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
            handle.write(f"exit_code={proc.returncode}\n")

        if proc.returncode != 0:
            job.status = "failed"
            job.message = f"factor_scores_failed:{proc.returncode}"
        else:
            job.status = "success"
        job.ended_at = datetime.utcnow()
        session.commit()
    except Exception as exc:
        session.rollback()
        job = session.get(FactorScoreJob, job_id)
        if job:
            job.status = "failed"
            job.message = f"factor_scores_error:{exc}"
            job.ended_at = datetime.utcnow()
            session.commit()
    finally:
        session.close()
