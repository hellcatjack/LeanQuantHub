from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import Algorithm, AlgorithmVersion, BacktestRun, Project, ProjectAlgorithmBinding
from app.schemas import (
    AlgorithmCreate,
    AlgorithmDiffOut,
    AlgorithmOut,
    AlgorithmPageOut,
    AlgorithmProjectCreate,
    AlgorithmSelfTestCreate,
    AlgorithmUpdate,
    AlgorithmVersionCreate,
    AlgorithmVersionDetailOut,
    AlgorithmVersionOut,
    AlgorithmVersionPageOut,
    BacktestOut,
    ProjectOut,
)
from app.services.audit_log import record_audit
from app.services.lean_runner import run_backtest

router = APIRouter(prefix="/api/algorithms", tags=["algorithms"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    if safe_page > total_pages:
        safe_page = total_pages
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


@router.get("", response_model=list[AlgorithmOut])
def list_algorithms():
    with get_session() as session:
        return session.query(Algorithm).order_by(Algorithm.updated_at.desc()).all()


@router.get("/page", response_model=AlgorithmPageOut)
def list_algorithms_page(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        total = session.query(Algorithm).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(Algorithm)
            .order_by(Algorithm.updated_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return AlgorithmPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )

@router.post("", response_model=AlgorithmOut)
def create_algorithm(payload: AlgorithmCreate):
    with get_session() as session:
        existing = session.query(Algorithm).filter(Algorithm.name == payload.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="算法名称已存在")
        algo = Algorithm(
            name=payload.name,
            description=payload.description,
            language=payload.language,
            file_path=payload.file_path,
            type_name=payload.type_name,
            version=payload.version,
        )
        session.add(algo)
        session.commit()
        session.refresh(algo)
        record_audit(
            session,
            action="algorithm.create",
            resource_type="algorithm",
            resource_id=algo.id,
            detail={"name": algo.name},
        )
        session.commit()
        return algo


@router.put("/{algorithm_id}", response_model=AlgorithmOut)
def update_algorithm(algorithm_id: int, payload: AlgorithmUpdate):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        if payload.name and payload.name != algo.name:
            existing = session.query(Algorithm).filter(Algorithm.name == payload.name).first()
            if existing and existing.id != algorithm_id:
                raise HTTPException(status_code=409, detail="算法名称已存在")
            algo.name = payload.name
        if payload.description is not None:
            algo.description = payload.description
        if payload.language:
            algo.language = payload.language
        if payload.file_path is not None:
            algo.file_path = payload.file_path
        if payload.type_name is not None:
            algo.type_name = payload.type_name
        if payload.version is not None:
            algo.version = payload.version
        session.commit()
        session.refresh(algo)
        record_audit(
            session,
            action="algorithm.update",
            resource_type="algorithm",
            resource_id=algo.id,
            detail={"name": algo.name},
        )
        session.commit()
        return algo


@router.get("/{algorithm_id}/versions", response_model=list[AlgorithmVersionOut])
def list_versions(algorithm_id: int):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        return (
            session.query(AlgorithmVersion)
            .filter(AlgorithmVersion.algorithm_id == algorithm_id)
            .order_by(AlgorithmVersion.created_at.desc())
            .all()
        )


@router.get("/{algorithm_id}/versions/page", response_model=AlgorithmVersionPageOut)
def list_versions_page(
    algorithm_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        total = (
            session.query(AlgorithmVersion)
            .filter(AlgorithmVersion.algorithm_id == algorithm_id)
            .count()
        )
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            session.query(AlgorithmVersion)
            .filter(AlgorithmVersion.algorithm_id == algorithm_id)
            .order_by(AlgorithmVersion.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return AlgorithmVersionPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/{algorithm_id}/versions/{version_id}", response_model=AlgorithmVersionDetailOut)
def get_version_detail(algorithm_id: int, version_id: int):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        version = session.get(AlgorithmVersion, version_id)
        if not version or version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=404, detail="算法版本不存在")
        return version


def _resolve_content(payload: AlgorithmVersionCreate) -> str | None:
    if payload.content:
        return payload.content
    if payload.file_path:
        path = Path(payload.file_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    return None


@router.post("/{algorithm_id}/versions", response_model=AlgorithmVersionOut)
def create_version(algorithm_id: int, payload: AlgorithmVersionCreate):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")

        content = _resolve_content(payload)
        content_hash = None
        params = payload.params if payload.params else None
        if content:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        elif params:
            serialized = json.dumps(params, ensure_ascii=False, sort_keys=True)
            content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        version = AlgorithmVersion(
            algorithm_id=algorithm_id,
            version=payload.version,
            description=payload.description,
            language=payload.language or algo.language,
            file_path=payload.file_path or algo.file_path,
            type_name=payload.type_name or algo.type_name,
            content_hash=content_hash,
            content=content,
            params=params,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        record_audit(
            session,
            action="algorithm.version.create",
            resource_type="algorithm_version",
            resource_id=version.id,
            detail={"algorithm_id": algorithm_id, "version": version.version},
        )
        session.commit()
        return version


@router.post(
    "/{algorithm_id}/versions/{version_id}/projects", response_model=ProjectOut
)
def create_project_from_version(
    algorithm_id: int, version_id: int, payload: AlgorithmProjectCreate
):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        version = session.get(AlgorithmVersion, version_id)
        if not version:
            raise HTTPException(status_code=404, detail="算法版本不存在")
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=400, detail="算法版本与算法不匹配")
        existing = session.query(Project).filter(Project.name == payload.name).first()
        if existing:
            raise HTTPException(status_code=409, detail="项目名称已存在")

        project = Project(name=payload.name, description=payload.description)
        session.add(project)
        session.commit()
        session.refresh(project)

        binding = ProjectAlgorithmBinding(
            project_id=project.id,
            algorithm_id=algorithm_id,
            algorithm_version_id=version_id,
            is_locked=payload.lock_version,
        )
        session.add(binding)
        record_audit(
            session,
            action="algorithm.project.create",
            resource_type="project",
            resource_id=project.id,
            detail={
                "algorithm_id": algorithm_id,
                "algorithm_version_id": version_id,
            },
        )
        session.commit()
        return project


@router.post("/{algorithm_id}/self-test", response_model=BacktestOut)
def run_self_test(
    algorithm_id: int,
    payload: AlgorithmSelfTestCreate,
    background_tasks: BackgroundTasks,
):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        version = None
        if payload.version_id:
            version = session.get(AlgorithmVersion, payload.version_id)
            if not version or version.algorithm_id != algorithm_id:
                raise HTTPException(status_code=404, detail="算法版本不存在")
        else:
            version = (
                session.query(AlgorithmVersion)
                .filter(AlgorithmVersion.algorithm_id == algorithm_id)
                .order_by(AlgorithmVersion.created_at.desc())
                .first()
            )
        if not version:
            raise HTTPException(status_code=400, detail="请先创建算法版本")

        project_name = f"AlgoSelfTest:{algorithm_id}"
        project = session.query(Project).filter(Project.name == project_name).first()
        if not project:
            project = Project(name=project_name, description=f"算法自测项目：{algo.name}")
            session.add(project)
            session.commit()
            session.refresh(project)

        binding = (
            session.query(ProjectAlgorithmBinding)
            .filter(ProjectAlgorithmBinding.project_id == project.id)
            .first()
        )
        if not binding:
            binding = ProjectAlgorithmBinding(
                project_id=project.id,
                algorithm_id=algorithm_id,
                algorithm_version_id=version.id,
                is_locked=False,
            )
            session.add(binding)
        else:
            binding.algorithm_id = algorithm_id
            binding.algorithm_version_id = version.id
            binding.is_locked = False

        params = payload.parameters.copy() if isinstance(payload.parameters, dict) else {}
        algo_params = params.get("algorithm_parameters")
        if not isinstance(algo_params, dict):
            algo_params = {}
        if version.params:
            algo_params.setdefault(
                "algo_params", json.dumps(version.params, ensure_ascii=False)
            )
        benchmark = (payload.benchmark or "SPY").strip().upper()
        if benchmark:
            algo_params["benchmark"] = benchmark
        params["algorithm_parameters"] = algo_params
        params["benchmark"] = benchmark

        params["algorithm_version_id"] = version.id
        params["algorithm_id"] = algorithm_id
        params["algorithm_version"] = version.version
        params["algorithm_language"] = version.language or algo.language
        if version.file_path or algo.file_path:
            params["algorithm_path"] = version.file_path or algo.file_path
        if version.type_name or algo.type_name:
            params["algorithm_type_name"] = version.type_name or algo.type_name

        run = BacktestRun(project_id=project.id, params=params)
        session.add(run)
        session.commit()
        session.refresh(run)
        record_audit(
            session,
            action="algorithm.selftest.create",
            resource_type="backtest",
            resource_id=run.id,
            detail={
                "algorithm_id": algorithm_id,
                "algorithm_version_id": version.id,
                "project_id": project.id,
            },
        )
        session.commit()

    background_tasks.add_task(run_backtest, run.id)
    return run


@router.get("/{algorithm_id}/diff", response_model=AlgorithmDiffOut)
def diff_versions(
    algorithm_id: int,
    from_id: int = Query(...),
    to_id: int = Query(...),
):
    with get_session() as session:
        algo = session.get(Algorithm, algorithm_id)
        if not algo:
            raise HTTPException(status_code=404, detail="算法不存在")
        from_version = session.get(AlgorithmVersion, from_id)
        to_version = session.get(AlgorithmVersion, to_id)
        if not from_version or not to_version:
            raise HTTPException(status_code=404, detail="版本不存在")
        if (
            from_version.algorithm_id != algorithm_id
            or to_version.algorithm_id != algorithm_id
        ):
            raise HTTPException(status_code=400, detail="版本不属于该算法")

        before = (from_version.content or "").splitlines()
        after = (to_version.content or "").splitlines()
        diff_lines = list(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"version_{from_version.id}",
                tofile=f"version_{to_version.id}",
                lineterm="",
            )
        )
        diff_sections = diff_lines

        params_before = json.dumps(
            from_version.params or {}, ensure_ascii=False, sort_keys=True, indent=2
        )
        params_after = json.dumps(
            to_version.params or {}, ensure_ascii=False, sort_keys=True, indent=2
        )
        if params_before != params_after:
            params_diff = list(
                difflib.unified_diff(
                    params_before.splitlines(),
                    params_after.splitlines(),
                    fromfile=f"params_{from_version.id}",
                    tofile=f"params_{to_version.id}",
                    lineterm="",
                )
            )
            diff_sections = diff_sections + [""] + params_diff

        diff = "\n".join(diff_sections)

        return AlgorithmDiffOut(
            algorithm_id=algorithm_id,
            from_version_id=from_id,
            to_version_id=to_id,
            diff=diff or "无差异",
        )
