from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

import math

from fastapi import APIRouter, HTTPException, Query

from app.db import get_session
from app.models import Algorithm, AlgorithmVersion, Project, ProjectAlgorithmBinding
from app.schemas import (
    AlgorithmCreate,
    AlgorithmDiffOut,
    AlgorithmOut,
    AlgorithmPageOut,
    AlgorithmProjectCreate,
    AlgorithmVersionCreate,
    AlgorithmVersionOut,
    AlgorithmVersionPageOut,
    ProjectOut,
)
from app.services.audit_log import record_audit

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
        if content:
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        version = AlgorithmVersion(
            algorithm_id=algorithm_id,
            version=payload.version,
            description=payload.description,
            language=payload.language or algo.language,
            file_path=payload.file_path or algo.file_path,
            type_name=payload.type_name or algo.type_name,
            content_hash=content_hash,
            content=content,
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
        diff_lines = difflib.unified_diff(
            before,
            after,
            fromfile=f"version_{from_version.id}",
            tofile=f"version_{to_version.id}",
            lineterm="",
        )
        diff = "\n".join(diff_lines)

        return AlgorithmDiffOut(
            algorithm_id=algorithm_id,
            from_version_id=from_id,
            to_version_id=to_id,
            diff=diff or "无差异",
        )
