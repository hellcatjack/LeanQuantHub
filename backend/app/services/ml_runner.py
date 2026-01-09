from __future__ import annotations

import csv
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db import SessionLocal
from app.models import (
    AlgorithmVersion,
    BacktestRun,
    MLPipelineRun,
    MLTrainJob,
    ProjectAlgorithmBinding,
)
from app.routes.backtests import (
    _collect_project_symbols as _collect_project_symbols_from_config,
    _collect_project_theme_map,
    _extract_pipeline_backtest_params,
)
from app.routes.projects import _resolve_project_config
from app.services.audit_log import record_audit
from app.services.lean_runner import run_backtest
from app.services.ml_quality import attach_train_quality

CANCEL_EXIT_CODE = 130


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


def _load_exclude_symbols(data_root: Path | None) -> set[str]:
    if not data_root:
        return set()
    exclude_paths = [
        data_root / "universe" / "exclude_symbols.csv",
        data_root / "universe" / "fundamentals_exclude.csv",
    ]
    symbols: set[str] = set()
    for path in exclude_paths:
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8-sig", errors="ignore") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    symbol = str(row.get("symbol") or "").strip().upper()
                    if symbol:
                        symbols.add(symbol)
        except OSError:
            continue
    return symbols


def _write_progress(path: Path, payload: dict[str, Any]) -> None:
    data = dict(payload)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_progress(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pipeline_auto_backtest_enabled(pipeline: MLPipelineRun) -> bool:
    params = pipeline.params if isinstance(pipeline.params, dict) else {}
    raw_flag = params.get("auto_backtest")
    if raw_flag is None:
        raw_flag = params.get("auto_backtest_on_train") or params.get("auto_run_backtest")
    if isinstance(raw_flag, str):
        return raw_flag.strip().lower() in ("1", "true", "yes", "y")
    return bool(raw_flag)


def _build_pipeline_backtest_params(
    session,
    project_id: int,
    pipeline: MLPipelineRun,
    score_path: Path | None,
) -> dict[str, Any]:
    params = _extract_pipeline_backtest_params(pipeline) or {}
    if not isinstance(params, dict):
        params = {}
    config = _resolve_project_config(session, project_id)
    if not params.get("benchmark"):
        params["benchmark"] = config.get("benchmark") or "SPY"
    algo_params = params.get("algorithm_parameters")
    if not isinstance(algo_params, dict):
        algo_params = {}
    if score_path and not str(algo_params.get("score_csv_path") or "").strip():
        algo_params["score_csv_path"] = str(score_path)
    if not str(algo_params.get("symbols") or "").strip():
        theme_symbols = _collect_project_symbols_from_config(config)
        if theme_symbols:
            algo_params["symbols"] = ",".join(theme_symbols)
    if not str(algo_params.get("theme_weights") or "").strip():
        symbol_theme_map, theme_weights = _collect_project_theme_map(config)
        if theme_weights:
            algo_params["theme_weights"] = json.dumps(theme_weights, ensure_ascii=False)
        if symbol_theme_map:
            algo_params["symbol_theme_map"] = json.dumps(
                symbol_theme_map, ensure_ascii=False
            )
    if not str(algo_params.get("theme_tilt") or "").strip():
        algo_params["theme_tilt"] = "0.5"
    backtest_cfg = config.get("backtest") if isinstance(config.get("backtest"), dict) else {}
    backtest_start = (
        config.get("backtest_start")
        or backtest_cfg.get("start")
        or backtest_cfg.get("start_date")
    )
    backtest_end = (
        config.get("backtest_end")
        or backtest_cfg.get("end")
        or backtest_cfg.get("end_date")
    )
    if backtest_start and not str(algo_params.get("backtest_start") or "").strip():
        algo_params["backtest_start"] = str(backtest_start)
    if backtest_end and not str(algo_params.get("backtest_end") or "").strip():
        algo_params["backtest_end"] = str(backtest_end)
    backtest_params = config.get("backtest_params")
    if isinstance(backtest_params, dict):
        for key, value in backtest_params.items():
            if key not in algo_params or str(algo_params.get(key) or "").strip() == "":
                algo_params[key] = value
    binding = (
        session.query(ProjectAlgorithmBinding)
        .filter(ProjectAlgorithmBinding.project_id == project_id)
        .first()
    )
    algorithm_version_id = binding.algorithm_version_id if binding else None
    if algorithm_version_id:
        algo_version = session.get(AlgorithmVersion, algorithm_version_id)
        if algo_version:
            if isinstance(algo_version.params, dict):
                for key, value in algo_version.params.items():
                    if key not in algo_params or algo_params.get(key) in (None, ""):
                        algo_params[key] = value
            params["algorithm_version_id"] = algo_version.id
            params["algorithm_id"] = algo_version.algorithm_id
            params["algorithm_version"] = algo_version.version
            if algo_version.language:
                params["algorithm_language"] = algo_version.language
            if algo_version.file_path:
                params["algorithm_path"] = algo_version.file_path
            if algo_version.type_name:
                params["algorithm_type_name"] = algo_version.type_name
    if algo_params:
        params["algorithm_parameters"] = algo_params
    return params


def _trigger_pipeline_backtest(train_job_id: int) -> None:
    session = SessionLocal()
    run_id: int | None = None
    try:
        job = session.get(MLTrainJob, train_job_id)
        if not job or not job.pipeline_id:
            return
        pipeline = session.get(MLPipelineRun, job.pipeline_id)
        if not pipeline:
            return
        if not _pipeline_auto_backtest_enabled(pipeline):
            return
        score_path = None
        if job.output_dir:
            candidate = Path(job.output_dir) / "scores.csv"
            if candidate.exists():
                score_path = candidate
        params = _build_pipeline_backtest_params(
            session, job.project_id, pipeline, score_path
        )
        if not params:
            return
        params.setdefault("pipeline_train_job_id", job.id)
        run = BacktestRun(
            project_id=job.project_id, params=params, pipeline_id=job.pipeline_id
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        record_audit(
            session,
            action="backtest.create",
            resource_type="backtest",
            resource_id=run.id,
            detail={"project_id": job.project_id, "source": "ml_train"},
        )
        session.commit()
        run_id = run.id
    finally:
        session.close()
    if run_id:
        run_backtest(run_id)


def _is_cancel_returncode(code: int | None) -> bool:
    return code == CANCEL_EXIT_CODE


def _parse_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return datetime.fromisoformat(text[:10]).date()
        except ValueError:
            return None


def _update_range(
    current: dict[str, datetime.date | None],
    start: datetime.date | None,
    end: datetime.date | None,
) -> None:
    if start and (current["start"] is None or start < current["start"]):
        current["start"] = start
    if end and (current["end"] is None or end > current["end"]):
        current["end"] = end


def _range_payload(
    ranges: dict[str, dict[str, datetime.date | None]],
    source: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"_source": source}
    for key, range_values in ranges.items():
        start = range_values["start"].isoformat() if range_values["start"] else None
        end = range_values["end"].isoformat() if range_values["end"] else None
        result[key] = {"start": start, "end": end}
    return result


def _derive_data_ranges(metrics: dict[str, Any], output_dir: str | None) -> dict[str, Any] | None:
    walk = metrics.get("walk_forward") or {}
    windows = walk.get("windows") if isinstance(walk, dict) else None
    if isinstance(windows, list) and windows:
        ranges = {
            "train": {"start": None, "end": None},
            "valid": {"start": None, "end": None},
            "test": {"start": None, "end": None},
        }
        for window in windows:
            if not isinstance(window, dict):
                continue
            train_start = _parse_date(window.get("train_start") or window.get("trainStart"))
            train_end = _parse_date(window.get("train_end") or window.get("trainEnd"))
            valid_start = _parse_date(window.get("valid_start") or window.get("validStart")) or train_end
            valid_end = _parse_date(window.get("valid_end") or window.get("validEnd"))
            test_start = (
                _parse_date(window.get("test_start") or window.get("testStart")) or valid_end
            )
            test_end = _parse_date(window.get("test_end") or window.get("testEnd")) or valid_end
            _update_range(ranges["train"], train_start, train_end)
            _update_range(ranges["valid"], valid_start, valid_end)
            _update_range(ranges["test"], test_start, test_end)
        return _range_payload(ranges, "walk_forward")

    if output_dir:
        payload_path = Path(output_dir) / "torch_payload.json"
        if payload_path.exists():
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            train_window = payload.get("train_window") if isinstance(payload, dict) else None
            if isinstance(train_window, dict):
                train_start = _parse_date(train_window.get("train_start"))
                train_end = _parse_date(train_window.get("train_end"))
                valid_end = _parse_date(train_window.get("valid_end"))
                test_end = _parse_date(train_window.get("test_end")) or valid_end
                ranges = {
                    "train": {"start": train_start, "end": train_end},
                    "valid": {"start": train_end, "end": valid_end},
                    "test": {"start": valid_end, "end": test_end},
                }
                return _range_payload(ranges, "payload")
    return None


def _attach_data_ranges(
    metrics: dict[str, Any] | None, output_dir: str | None
) -> dict[str, Any] | None:
    base = dict(metrics) if metrics else {}
    data_ranges = _derive_data_ranges(base, output_dir)
    if not data_ranges:
        return metrics
    base["data_ranges"] = data_ranges
    return base


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
    from app.routes import projects as project_routes

    base = _load_base_config()
    project_config, symbols = _collect_project_symbols(session, project_id)
    data_root = project_routes._get_data_root()

    benchmark = str(project_config.get("benchmark") or base.get("benchmark_symbol") or "SPY")
    benchmark = benchmark.strip().upper() or "SPY"
    if symbols:
        base["symbols"] = symbols
    if benchmark and benchmark not in base.get("symbols", []):
        base["symbols"] = [benchmark] + list(base.get("symbols", []))
    base["benchmark_symbol"] = benchmark
    exclude_symbols = _load_exclude_symbols(data_root)
    if exclude_symbols:
        filtered = [symbol for symbol in base.get("symbols", []) if symbol not in exclude_symbols]
        if benchmark and benchmark not in filtered:
            filtered = [benchmark] + filtered
        base["symbols"] = filtered
        base.setdefault("meta", {})
        base["meta"]["excluded_symbols_count"] = len(exclude_symbols)

    if overrides:
        walk_forward = base.get("walk_forward") or {}
        if overrides.get("train_years") is not None:
            walk_forward["train_years"] = int(overrides["train_years"])
        if overrides.get("valid_months") is not None:
            walk_forward["valid_months"] = int(overrides["valid_months"])
        if overrides.get("test_months") is not None:
            walk_forward["test_months"] = int(overrides["test_months"])
        if overrides.get("step_months") is not None:
            walk_forward["step_months"] = int(overrides["step_months"])
        base["walk_forward"] = walk_forward
        if overrides.get("label_horizon_days") is not None:
            base["label_horizon_days"] = int(overrides["label_horizon_days"])
        if overrides.get("train_start_year") is not None:
            base["train_start_year"] = int(overrides["train_start_year"])
        if overrides.get("device"):
            base["device"] = str(overrides["device"]).strip()
        if overrides.get("model_type"):
            base["model_type"] = str(overrides["model_type"]).strip()
        if isinstance(overrides.get("model_params"), dict):
            base["model_params"] = dict(overrides["model_params"])

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
    lgbm_model_path = output_model_dir / "lgbm_model.txt"
    payload_path = output_model_dir / "torch_payload.json"
    metrics_path = output_model_dir / "torch_metrics.json"
    scores_path = output_dir / "scores.csv"

    if model_path.exists():
        shutil.copy2(model_path, model_dir / "torch_model.pt")
        job.model_path = str(model_dir / "torch_model.pt")
    if lgbm_model_path.exists():
        shutil.copy2(lgbm_model_path, model_dir / "lgbm_model.txt")
        if not job.model_path:
            job.model_path = str(model_dir / "lgbm_model.txt")
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
        if job.status in {"canceled", "cancel_requested"}:
            if job.status == "cancel_requested":
                job.status = "canceled"
            if not job.ended_at:
                job.ended_at = datetime.utcnow()
            session.commit()
            return

        job.status = "running"
        job.started_at = datetime.utcnow()
        session.commit()

        output_dir = Path(settings.artifact_root) / f"ml_job_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "ml_train.log"
        progress_path = output_dir / "progress.json"
        cancel_path = output_dir / "cancel.flag"

        job.output_dir = str(output_dir)
        job.log_path = str(log_path)
        session.commit()
        _write_progress(progress_path, {"phase": "queued", "progress": 0.0})

        session.refresh(job)
        if job.status in {"canceled", "cancel_requested"}:
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            current = _read_progress(progress_path) or {"progress": 0.0}
            current["phase"] = "canceled"
            _write_progress(progress_path, current)
            record_audit(
                session,
                action="ml.train.canceled",
                resource_type="ml_train_job",
                resource_id=job.id,
                detail={"project_id": job.project_id, "status": job.status},
            )
            session.commit()
            return

        if cancel_path.exists():
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            current = _read_progress(progress_path) or {"progress": 0.0}
            current["phase"] = "canceled"
            _write_progress(progress_path, current)
            record_audit(
                session,
                action="ml.train.canceled",
                resource_type="ml_train_job",
                resource_id=job.id,
                detail={"project_id": job.project_id, "status": job.status},
            )
            session.commit()
            return

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
        cmd += ["--cancel-path", str(cancel_path)]
        if rolling_scores:
            cmd += ["--scores-output", str(scores_path)]

        with log_path.open("w", encoding="utf-8") as handle:
            handle.write(f"[train] running: {' '.join(cmd)}\n")
            proc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
            handle.write(f"[train] exit={proc.returncode}\n")
        if _is_cancel_returncode(proc.returncode):
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            current = _read_progress(progress_path) or {"progress": 0.0}
            current["phase"] = "canceled"
            _write_progress(progress_path, current)
            record_audit(
                session,
                action="ml.train.canceled",
                resource_type="ml_train_job",
                resource_id=job.id,
                detail={"project_id": job.project_id, "status": job.status},
            )
            session.commit()
            return
        if proc.returncode != 0:
            raise RuntimeError(f"train_failed:{proc.returncode}")
        if cancel_path.exists():
            job.status = "canceled"
            job.message = "用户取消"
            job.ended_at = datetime.utcnow()
            current = _read_progress(progress_path) or {"progress": 0.0}
            current["phase"] = "canceled"
            _write_progress(progress_path, current)
            record_audit(
                session,
                action="ml.train.canceled",
                resource_type="ml_train_job",
                resource_id=job.id,
                detail={"project_id": job.project_id, "status": job.status},
            )
            session.commit()
            return
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
            score_cmd += ["--cancel-path", str(cancel_path)]

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[score] running: {' '.join(score_cmd)}\n")
                proc = subprocess.run(score_cmd, stdout=handle, stderr=subprocess.STDOUT, check=False)
                handle.write(f"[score] exit={proc.returncode}\n")
            if _is_cancel_returncode(proc.returncode):
                job.status = "canceled"
                job.message = "用户取消"
                job.ended_at = datetime.utcnow()
                current = _read_progress(progress_path) or {"progress": 0.0}
                current["phase"] = "canceled"
                _write_progress(progress_path, current)
                record_audit(
                    session,
                    action="ml.train.canceled",
                    resource_type="ml_train_job",
                    resource_id=job.id,
                    detail={"project_id": job.project_id, "status": job.status},
                )
                session.commit()
                return
            if proc.returncode != 0:
                raise RuntimeError(f"score_failed:{proc.returncode}")
            _write_progress(progress_path, {"phase": "done", "progress": 1.0})

        metrics_path = Path(config["output_dir"]) / "torch_metrics.json"
        metrics: dict[str, Any] | None = None
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics = _attach_data_ranges(metrics, config.get("output_dir"))
        metrics = attach_train_quality(metrics, config)
        if metrics_path.exists() and metrics is not None:
            metrics_path.write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
            )

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
        _trigger_pipeline_backtest(job.id)
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
