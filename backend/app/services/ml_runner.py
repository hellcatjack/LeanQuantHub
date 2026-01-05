from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import SessionLocal
from app.models import MLTrainJob
from app.services.audit_log import record_audit


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_ml_python() -> str:
    if settings.ml_python_path:
        return settings.ml_python_path
    candidate = _project_root() / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return "python3"


def _load_base_config() -> dict[str, Any]:
    config_path = _project_root() / "ml" / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
        return {
            "output_dir": "ml/models",
            "benchmark_symbol": "SPY",
            "symbols": [],
            "vendor_preference": ["Alpha", "Lean"],
            "label_horizon_days": 20,
            "label_price": "open",
            "label_start_offset": 1,
            "pit_fundamentals": {
                "enabled": True,
                "dir": "",
                "min_coverage": 0.05,
                "coverage_action": "warn",
                "missing_policy": "fill_zero",
                "sample_on_snapshot": True,
                "start": "",
                "end": "",
            },
            "walk_forward": {"train_years": 8, "valid_months": 12},
            "torch": {"hidden": [64, 32], "dropout": 0.1, "lr": 0.001, "epochs": 50},
        }


def _write_progress(path: Path, payload: dict[str, Any]) -> None:
    data = dict(payload)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_project_symbols(session, project_id: int) -> tuple[dict[str, Any], list[str]]:
    from app.routes import projects as project_routes

    config = project_routes._resolve_project_config(session, project_id)
    data_root = project_routes._get_data_root()
    universe_path = data_root / "universe" / "universe.csv"
    rows = project_routes._safe_read_csv(universe_path)
    theme_index = project_routes._build_theme_index(config)
    resolved = project_routes._resolve_theme_memberships(rows, theme_index)
    symbols = sorted({symbol for values in resolved.values() for symbol in values})
    return config, symbols


def build_ml_config(
    session,
    project_id: int,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    base = _load_base_config()
    project_config, symbols = _collect_project_symbols(session, project_id)

    benchmark = str(project_config.get("benchmark") or base.get("benchmark_symbol") or "SPY")
    benchmark = benchmark.strip().upper() or "SPY"
    if symbols:
        base["symbols"] = symbols
    if benchmark and benchmark not in base.get("symbols", []):
        base["symbols"] = [benchmark] + list(base.get("symbols", []))
    base["benchmark_symbol"] = benchmark

    if overrides:
        walk_forward = base.get("walk_forward") or {}
        if overrides.get("train_years") is not None:
            walk_forward["train_years"] = int(overrides["train_years"])
        if overrides.get("valid_months") is not None:
            walk_forward["valid_months"] = int(overrides["valid_months"])
        base["walk_forward"] = walk_forward
        if overrides.get("label_horizon_days") is not None:
            base["label_horizon_days"] = int(overrides["label_horizon_days"])
        if overrides.get("device"):
            base["device"] = str(overrides["device"]).strip()

    base.setdefault("meta", {})
    base["meta"]["project_id"] = project_id
    base["meta"]["symbol_count"] = len(base.get("symbols", []))
    return base


def activate_job(session, job: MLTrainJob) -> None:
    if not job.output_dir:
        raise RuntimeError("missing_output_dir")
    output_dir = Path(job.output_dir)
    model_dir = _project_root() / "ml" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    output_model_dir = output_dir / "output"
    model_path = output_model_dir / "torch_model.pt"
    payload_path = output_model_dir / "torch_payload.json"
    metrics_path = output_model_dir / "torch_metrics.json"
    scores_path = output_dir / "scores.csv"

    if model_path.exists():
        shutil.copy2(model_path, model_dir / "torch_model.pt")
        job.model_path = str(model_dir / "torch_model.pt")
    if payload_path.exists():
        shutil.copy2(payload_path, model_dir / "torch_payload.json")
        job.payload_path = str(model_dir / "torch_payload.json")
    if metrics_path.exists():
        shutil.copy2(metrics_path, model_dir / "torch_metrics.json")
    if scores_path.exists():
        shutil.copy2(scores_path, model_dir / "scores.csv")
        job.scores_path = str(model_dir / "scores.csv")

    session.query(MLTrainJob).filter(
        MLTrainJob.project_id == job.project_id,
        MLTrainJob.id != job.id,
        MLTrainJob.is_active.is_(True),
    ).update({"is_active": False})
    job.is_active = True


def run_ml_train(job_id: int) -> None:
    session = SessionLocal()
    try:
        job = session.get(MLTrainJob, job_id)
        if not job:
            return

        job.status = "running"
        job.started_at = datetime.utcnow()
        session.commit()

        output_dir = Path(settings.artifact_root) / f"ml_job_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "ml_train.log"
        progress_path = output_dir / "progress.json"

        job.output_dir = str(output_dir)
        job.log_path = str(log_path)
        session.commit()
        _write_progress(progress_path, {"phase": "queued", "progress": 0.0})

        config = dict(job.config or {})
        config["output_dir"] = str(output_dir / "output")
        config_path = output_dir / "ml_config.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        ml_root = _project_root() / "ml"
        train_script = ml_root / "train_torch.py"
        predict_script = ml_root / "predict_torch.py"
        if not train_script.exists() or not predict_script.exists():
            raise RuntimeError("ml_scripts_missing")

        scores_path = output_dir / "scores.csv"
        walk_config = config.get("walk_forward") or {}
        try:
            test_months = int(walk_config.get("test_months") or 0)
        except (TypeError, ValueError):
            test_months = 0
        try:
            step_months = int(walk_config.get("step_months") or test_months)
        except (TypeError, ValueError):
            step_months = test_months
        rolling_scores = test_months > 0 and step_months > 0

        cmd = [
            _resolve_ml_python(),
            str(train_script),
            "--config",
            str(config_path),
        ]
        if settings.data_root:
            cmd += ["--data-root", settings.data_root]
        device = str(config.get("device") or "auto")
        cmd += ["--device", device]
        cmd += ["--progress-path", str(progress_path)]
        if rolling_scores:
            cmd += ["--scores-output", str(scores_path)]

        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"[train] running: {' '.join(cmd)}\n")
            proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
            handle.write(f"[train] exit={proc.returncode}\n")
        if proc.returncode != 0:
            raise RuntimeError(f"train_failed:{proc.returncode}")
        if rolling_scores:
            if not scores_path.exists():
                raise RuntimeError("score_failed:missing_scores")
        else:
            _write_progress(progress_path, {"phase": "score", "progress": 0.9})
            score_cmd = [
                _resolve_ml_python(),
                str(predict_script),
                "--config",
                str(config_path),
                "--output",
                str(scores_path),
            ]
            if settings.data_root:
                score_cmd += ["--data-root", settings.data_root]
            score_cmd += ["--device", device]

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[score] running: {' '.join(score_cmd)}\n")
                proc = subprocess.run(score_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
                handle.write(f"[score] exit={proc.returncode}\n")
            if proc.returncode != 0:
                raise RuntimeError(f"score_failed:{proc.returncode}")
            _write_progress(progress_path, {"phase": "done", "progress": 1.0})

        metrics_path = Path(config["output_dir"]) / "torch_metrics.json"
        metrics: dict[str, Any] | None = None
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))

        job.output_dir = str(output_dir)
        job.log_path = str(log_path)
        job.metrics = metrics
        activate_job(session, job)
        job.status = "success"
        job.ended_at = datetime.utcnow()
        _write_progress(progress_path, {"phase": "done", "progress": 1.0})

        record_audit(
            session,
            action="ml.train.success",
            resource_type="ml_train_job",
            resource_id=job.id,
            detail={"project_id": job.project_id, "status": job.status},
        )
        session.commit()
    except Exception as exc:
        job = session.get(MLTrainJob, job_id)
        if job:
            job.status = "failed"
            job.message = str(exc)
            job.ended_at = datetime.utcnow()
            if job.output_dir:
                progress_path = Path(job.output_dir) / "progress.json"
                _write_progress(
                    progress_path,
                    {"phase": "failed", "progress": 1.0, "error": str(exc)},
                )
            record_audit(
                session,
                action="ml.train.failed",
                resource_type="ml_train_job",
                resource_id=job.id,
                detail={"error": str(exc)},
            )
            session.commit()
    finally:
        session.close()
