from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.db import get_session
from app.models import BacktestRun, MLPipelineRun, MLTrainJob, Project
from app.schemas import (
    MLPipelineCreate,
    MLPipelineDetailOut,
    MLPipelineListItem,
    MLPipelineOut,
    MLPipelineUpdate,
    PipelineBacktestOut,
)
from app.services.audit_log import record_audit
from app.services.ml_quality import (
    DEFAULT_TRAIN_QUALITY_CONFIG,
    DEFAULT_TRAIN_QUALITY_WEIGHTS,
    compute_train_quality,
)
from app.services.pipeline_scoring import (
    DEFAULT_BACKTEST_SCORE_SCALES,
    DEFAULT_BACKTEST_SCORE_WEIGHTS,
    DEFAULT_COMBINED_WEIGHT,
    compute_backtest_score,
    compute_combined_score,
)

router = APIRouter(prefix="/api/ml/pipelines", tags=["ml-pipelines"])


def _ensure_scoring_params(params: dict[str, Any]) -> dict[str, Any]:
    scoring = params.get("scoring")
    if not isinstance(scoring, dict):
        scoring = {}
    scoring.setdefault("train_weights", dict(DEFAULT_TRAIN_QUALITY_WEIGHTS))
    scoring.setdefault("curve_gap_scale", DEFAULT_TRAIN_QUALITY_CONFIG.get("curve_gap_scale"))
    scoring.setdefault("backtest_weights", dict(DEFAULT_BACKTEST_SCORE_WEIGHTS))
    scoring.setdefault("backtest_scales", dict(DEFAULT_BACKTEST_SCORE_SCALES))
    scoring.setdefault("combined_weight", DEFAULT_COMBINED_WEIGHT)
    params["scoring"] = scoring
    return params


def _extract_train_score(job: MLTrainJob, pipeline: MLPipelineRun) -> float | None:
    metrics = job.metrics if isinstance(job.metrics, dict) else None
    if not isinstance(metrics, dict):
        return None
    params = pipeline.params if isinstance(pipeline.params, dict) else {}
    scoring = params.get("scoring") if isinstance(params.get("scoring"), dict) else {}
    train_weights = (
        scoring.get("train_weights")
        if isinstance(scoring.get("train_weights"), dict)
        else None
    )
    gap_scale = scoring.get("curve_gap_scale")
    config = dict(DEFAULT_TRAIN_QUALITY_CONFIG)
    if gap_scale is not None:
        try:
            config["curve_gap_scale"] = float(gap_scale)
        except (TypeError, ValueError):
            pass
    result = compute_train_quality(metrics, weights=train_weights, config=config)
    if result is None or result.score is None:
        value = metrics.get("quality_score")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    return result.score


def _score_backtest(run: BacktestRun, pipeline: MLPipelineRun) -> dict[str, Any] | None:
    params = pipeline.params if isinstance(pipeline.params, dict) else {}
    scoring = params.get("scoring") if isinstance(params.get("scoring"), dict) else {}
    backtest_weights = scoring.get("backtest_weights") if isinstance(scoring.get("backtest_weights"), dict) else None
    backtest_scales = scoring.get("backtest_scales") if isinstance(scoring.get("backtest_scales"), dict) else None
    return compute_backtest_score(run.metrics if isinstance(run.metrics, dict) else None, backtest_weights, backtest_scales)


def _summarize_pipeline(pipeline: MLPipelineRun, train_jobs: list[MLTrainJob], backtests: list[BacktestRun]) -> MLPipelineListItem:
    best_train_score = None
    best_train_job_id = None
    for job in train_jobs:
        score = _extract_train_score(job, pipeline)
        if score is None:
            continue
        if best_train_score is None or score > best_train_score:
            best_train_score = score
            best_train_job_id = job.id

    best_backtest_score = None
    best_backtest_id = None
    for run in backtests:
        detail = _score_backtest(run, pipeline)
        score = detail.get("score") if isinstance(detail, dict) else None
        if score is None:
            continue
        if best_backtest_score is None or score > best_backtest_score:
            best_backtest_score = score
            best_backtest_id = run.id

    params = pipeline.params if isinstance(pipeline.params, dict) else {}
    scoring = params.get("scoring") if isinstance(params.get("scoring"), dict) else {}
    combined_weight = scoring.get("combined_weight")
    combined_score = compute_combined_score(best_train_score, best_backtest_score, combined_weight)

    item = MLPipelineListItem.model_validate(pipeline, from_attributes=True)
    item.train_job_count = len(train_jobs)
    item.backtest_count = len(backtests)
    item.best_train_score = best_train_score
    item.best_backtest_score = best_backtest_score
    item.combined_score = combined_score
    item.best_train_job_id = best_train_job_id
    item.best_backtest_run_id = best_backtest_id
    return item


@router.post("", response_model=MLPipelineListItem)
def create_pipeline(payload: MLPipelineCreate):
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        params = payload.params if isinstance(payload.params, dict) else {}
        params = _ensure_scoring_params(params)
        pipeline = MLPipelineRun(
            project_id=payload.project_id,
            name=payload.name,
            status="created",
            params=params,
            notes=payload.notes,
            created_at=datetime.utcnow(),
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)
        record_audit(
            session,
            action="ml.pipeline.create",
            resource_type="ml_pipeline",
            resource_id=pipeline.id,
            detail={"project_id": pipeline.project_id},
        )
        session.commit()
        return _summarize_pipeline(pipeline, [], [])


@router.patch("/{pipeline_id}", response_model=MLPipelineOut)
def update_pipeline(pipeline_id: int, payload: MLPipelineUpdate):
    with get_session() as session:
        pipeline = session.get(MLPipelineRun, pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline 不存在")
        if payload.name is not None:
            pipeline.name = payload.name
        if payload.notes is not None:
            pipeline.notes = payload.notes
        if payload.status is not None:
            pipeline.status = payload.status
        if payload.params is not None:
            params = payload.params if isinstance(payload.params, dict) else {}
            pipeline.params = _ensure_scoring_params(params)
        session.commit()
        session.refresh(pipeline)
        record_audit(
            session,
            action="ml.pipeline.update",
            resource_type="ml_pipeline",
            resource_id=pipeline.id,
            detail={"project_id": pipeline.project_id},
        )
        session.commit()
        return pipeline


@router.get("", response_model=list[MLPipelineListItem])
def list_pipelines(project_id: int | None = Query(None)):
    with get_session() as session:
        query = session.query(MLPipelineRun)
        if project_id:
            query = query.filter(MLPipelineRun.project_id == project_id)
        pipelines = query.order_by(MLPipelineRun.created_at.desc()).all()
        if not pipelines:
            return []
        pipeline_ids = [pipeline.id for pipeline in pipelines]
        train_jobs = (
            session.query(MLTrainJob)
            .filter(MLTrainJob.pipeline_id.in_(pipeline_ids))
            .order_by(MLTrainJob.created_at.desc())
            .all()
        )
        backtests = (
            session.query(BacktestRun)
            .filter(BacktestRun.pipeline_id.in_(pipeline_ids))
            .order_by(BacktestRun.created_at.desc())
            .all()
        )
        trains_by_pipeline: dict[int, list[MLTrainJob]] = {pid: [] for pid in pipeline_ids}
        for job in train_jobs:
            if job.pipeline_id is not None:
                trains_by_pipeline.setdefault(job.pipeline_id, []).append(job)
        backtests_by_pipeline: dict[int, list[BacktestRun]] = {pid: [] for pid in pipeline_ids}
        for run in backtests:
            if run.pipeline_id is not None:
                backtests_by_pipeline.setdefault(run.pipeline_id, []).append(run)

        items: list[MLPipelineListItem] = []
        for pipeline in pipelines:
            items.append(
                _summarize_pipeline(
                    pipeline,
                    trains_by_pipeline.get(pipeline.id, []),
                    backtests_by_pipeline.get(pipeline.id, []),
                )
            )
        return items


@router.get("/{pipeline_id}", response_model=MLPipelineDetailOut)
def get_pipeline(pipeline_id: int):
    with get_session() as session:
        pipeline = session.get(MLPipelineRun, pipeline_id)
        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline 不存在")
        train_jobs = (
            session.query(MLTrainJob)
            .filter(MLTrainJob.pipeline_id == pipeline_id)
            .order_by(MLTrainJob.created_at.desc())
            .all()
        )
        backtests = (
            session.query(BacktestRun)
            .filter(BacktestRun.pipeline_id == pipeline_id)
            .order_by(BacktestRun.created_at.desc())
            .all()
        )

        best_train_score = None
        for job in train_jobs:
            score = _extract_train_score(job, pipeline)
            if score is None:
                continue
            if best_train_score is None or score > best_train_score:
                best_train_score = score

        backtest_items: list[PipelineBacktestOut] = []
        backtest_scores: list[float] = []
        for run in backtests:
            detail = _score_backtest(run, pipeline)
            score = detail.get("score") if isinstance(detail, dict) else None
            if score is not None:
                backtest_scores.append(score)
            out = PipelineBacktestOut.model_validate(run, from_attributes=True)
            out.score = score
            out.score_detail = detail
            backtest_items.append(out)

        params = pipeline.params if isinstance(pipeline.params, dict) else {}
        scoring = params.get("scoring") if isinstance(params.get("scoring"), dict) else {}
        combined_weight = scoring.get("combined_weight")
        best_backtest_score = max(backtest_scores) if backtest_scores else None
        combined_score = compute_combined_score(best_train_score, best_backtest_score, combined_weight)

        train_summary = {
            "best_score": best_train_score,
            "job_count": len(train_jobs),
            "weights": scoring.get("train_weights"),
            "curve_gap_scale": scoring.get("curve_gap_scale"),
        }
        backtest_summary = {
            "best_score": best_backtest_score,
            "run_count": len(backtests),
            "weights": scoring.get("backtest_weights"),
            "scales": scoring.get("backtest_scales"),
        }

        payload = MLPipelineDetailOut.model_validate(pipeline, from_attributes=True)
        payload.train_jobs = train_jobs
        payload.backtests = backtest_items
        payload.train_score_summary = train_summary
        backtest_summary["combined_score"] = combined_score
        backtest_summary["combined_weight"] = combined_weight
        payload.backtest_score_summary = backtest_summary
        return payload
