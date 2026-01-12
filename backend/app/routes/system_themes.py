from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.db import get_session
from app.models import (
    Project,
    ProjectSystemThemeBinding,
    ProjectVersion,
    SystemTheme,
    SystemThemeVersion,
    ThemeChangeReport,
)
from app.schemas import (
    SystemThemeImportOut,
    SystemThemeImportRequest,
    SystemThemeOut,
    SystemThemePageOut,
    SystemThemeRefreshOut,
    SystemThemeVersionOut,
    SystemThemeVersionPageOut,
    ThemeChangeReportOut,
    ThemeChangeReportPageOut,
)
from app.services.audit_log import record_audit

router = APIRouter(prefix="/api/system-themes", tags=["system-themes"])

MAX_PAGE_SIZE = 200
PROJECT_CONFIG_TAG = "project_config"


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
    safe_page = max(1, min(page, total_pages))
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


def _get_data_root() -> Path:
    if settings.data_root:
        return Path(settings.data_root)
    env_root = os.environ.get("DATA_ROOT")
    if env_root:
        return Path(env_root)
    return Path("C:/work/stocks/data")


def _load_theme_keywords() -> list[dict[str, Any]]:
    base_dir = Path(__file__).resolve().parents[3]
    theme_path = base_dir / "configs" / "theme_keywords.json"
    if not theme_path.exists():
        return []
    try:
        payload = json.loads(theme_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(payload.get("categories") or [])


def _load_sp500_payloads() -> dict[str, dict[str, Any]]:
    data_root = _get_data_root()
    membership_path = data_root / "universe" / "sp500_membership.csv"
    universe_path = data_root / "universe" / "universe.csv"
    payloads: dict[str, dict[str, Any]] = {
        "SP500_CURRENT": {"key": "SP500_CURRENT", "label": "S&P500现有成分", "symbols": []},
        "SP500_FORMER": {
            "key": "SP500_FORMER",
            "label": "S&P500历史成分（现存）",
            "symbols": [],
        },
    }

    def load_rows(path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    rows = load_rows(membership_path)
    if rows:
        current: set[str] = set()
        all_symbols: set[str] = set()
        for row in rows:
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            all_symbols.add(symbol)
            end_date = (row.get("end_date") or row.get("end") or "").strip()
            if not end_date:
                current.add(symbol)
        payloads["SP500_CURRENT"]["symbols"] = sorted(current)
        payloads["SP500_FORMER"]["symbols"] = sorted(all_symbols - current)
        return payloads

    rows = load_rows(universe_path)
    if not rows:
        return {}
    current: set[str] = set()
    former: set[str] = set()
    for row in rows:
        in_history = (row.get("in_sp500_history") or "").strip()
        if in_history != "1":
            continue
        symbol = (row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        end_date = (row.get("end_date") or "").strip()
        if end_date:
            former.add(symbol)
        else:
            current.add(symbol)
    payloads["SP500_CURRENT"]["symbols"] = sorted(current)
    payloads["SP500_FORMER"]["symbols"] = sorted(former)
    return payloads


def _load_data_complete_payload() -> dict[str, Any] | None:
    data_root = _get_data_root()
    path = data_root / "universe" / "data_complete_symbols.csv"
    if not path.exists():
        return None
    symbols: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol:
                symbols.append(symbol)
    symbols = sorted({sym for sym in symbols if sym})
    if not symbols:
        return None
    return {
        "key": "DATA_COMPLETE",
        "label": "数据完整（在市）",
        "manual": symbols,
    }


def _normalize_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()]
    return []


def _build_payload_from_category(category: dict[str, Any]) -> dict[str, Any]:
    key = str(category.get("key", "")).strip()
    label = str(category.get("label", "")).strip() or key
    manual = _normalize_list(category.get("manual"))
    manual_pinned = _normalize_list(category.get("manualPinned"))
    merged_manual = list(dict.fromkeys(manual_pinned + manual))
    return {
        "key": key,
        "label": label,
        "keywords": _normalize_list(category.get("keywords")),
        "manual": merged_manual,
        "exclude": _normalize_list(category.get("exclude")),
    }


def _get_latest_version(session, theme_id: int) -> SystemThemeVersion | None:
    return (
        session.query(SystemThemeVersion)
        .filter(SystemThemeVersion.theme_id == theme_id)
        .order_by(SystemThemeVersion.created_at.desc())
        .first()
    )


def _ensure_system_themes(session) -> None:
    themes = session.query(SystemTheme).all()
    existing = {theme.key: theme for theme in themes}
    sp500_payloads = _load_sp500_payloads()
    data_complete_payload = _load_data_complete_payload()

    if not existing:
        for category in _load_theme_keywords():
            key = str(category.get("key", "")).strip()
            if not key:
                continue
            label = str(category.get("label", "")).strip() or key
            theme = SystemTheme(key=key, label=label, source="config")
            session.add(theme)
            session.flush()
            payload = _build_payload_from_category(category)
            version = SystemThemeVersion(
                theme_id=theme.id,
                version=datetime.utcnow().isoformat(),
                payload=payload,
            )
            session.add(version)
        for key, payload in sp500_payloads.items():
            label = payload.get("label") or key
            theme = SystemTheme(key=key, label=label, source="membership")
            session.add(theme)
            session.flush()
            session.add(
                SystemThemeVersion(
                    theme_id=theme.id,
                    version=datetime.utcnow().isoformat(),
                    payload=payload,
                )
            )
        if data_complete_payload:
            key = data_complete_payload.get("key") or "DATA_COMPLETE"
            label = data_complete_payload.get("label") or key
            theme = SystemTheme(key=key, label=label, source="data_complete")
            session.add(theme)
            session.flush()
            session.add(
                SystemThemeVersion(
                    theme_id=theme.id,
                    version=datetime.utcnow().isoformat(),
                    payload=data_complete_payload,
                )
            )
        session.commit()
        return

    for category in _load_theme_keywords():
        key = str(category.get("key", "")).strip()
        if not key:
            continue
        theme = existing.get(key)
        if not theme:
            label = str(category.get("label", "")).strip() or key
            theme = SystemTheme(key=key, label=label, source="config")
            session.add(theme)
            session.flush()
        else:
            label = str(category.get("label", "")).strip() or key
            if label and label != theme.label:
                theme.label = label
        latest = _get_latest_version(session, theme.id)
        if not latest:
            payload = _build_payload_from_category(category)
            session.add(
                SystemThemeVersion(
                    theme_id=theme.id,
                    version=datetime.utcnow().isoformat(),
                    payload=payload,
                )
            )

    for key, payload in sp500_payloads.items():
        theme = existing.get(key)
        if not theme:
            label = payload.get("label") or key
            theme = SystemTheme(key=key, label=label, source="membership")
            session.add(theme)
            session.flush()
            existing[key] = theme
        else:
            label = payload.get("label") or key
            if label and label != theme.label:
                theme.label = label
        latest = _get_latest_version(session, theme.id)
        if not latest or (latest.payload or {}) != payload:
            session.add(
                SystemThemeVersion(
                    theme_id=theme.id,
                    version=datetime.utcnow().isoformat(),
                    payload=payload,
                )
            )

    if data_complete_payload:
        key = data_complete_payload.get("key") or "DATA_COMPLETE"
        theme = existing.get(key)
        if not theme:
            label = data_complete_payload.get("label") or key
            theme = SystemTheme(key=key, label=label, source="data_complete")
            session.add(theme)
            session.flush()
            existing[key] = theme
        else:
            label = data_complete_payload.get("label") or key
            if label and label != theme.label:
                theme.label = label
        latest = _get_latest_version(session, theme.id)
        if not latest or (latest.payload or {}) != data_complete_payload:
            session.add(
                SystemThemeVersion(
                    theme_id=theme.id,
                    version=datetime.utcnow().isoformat(),
                    payload=data_complete_payload,
                )
            )

    sp500_other = existing.get("SP500_OTHER")
    sp500_current = existing.get("SP500_CURRENT")
    if sp500_other and sp500_current:
        latest_current = _get_latest_version(session, sp500_current.id)
        if not latest_current:
            payload = sp500_payloads.get("SP500_CURRENT")
            if payload:
                latest_current = SystemThemeVersion(
                    theme_id=sp500_current.id,
                    version=datetime.utcnow().isoformat(),
                    payload=payload,
                )
                session.add(latest_current)
                session.flush()
        if not latest_current:
            session.commit()
            return
        bindings = (
            session.query(ProjectSystemThemeBinding)
            .filter(ProjectSystemThemeBinding.theme_id == sp500_other.id)
            .all()
        )
        for binding in bindings:
            existing_binding = (
                session.query(ProjectSystemThemeBinding)
                .filter(
                    ProjectSystemThemeBinding.project_id == binding.project_id,
                    ProjectSystemThemeBinding.theme_id == sp500_current.id,
                )
                .first()
            )
            if existing_binding:
                session.delete(binding)
                continue
            binding.theme_id = sp500_current.id
            binding.version_id = latest_current.id
            binding.updated_at = datetime.utcnow()

        session.flush()
        session.query(SystemThemeVersion).filter(
            SystemThemeVersion.theme_id == sp500_other.id
        ).delete()
        session.query(SystemTheme).filter(SystemTheme.id == sp500_other.id).delete()
    session.commit()


def _build_system_base(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": payload.get("label") or payload.get("key"),
        "keywords": _normalize_list(payload.get("keywords")),
        "manual": _normalize_list(payload.get("manual")),
        "exclude": _normalize_list(payload.get("exclude")),
    }


def _diff_payload(prev: dict[str, Any] | None, next_payload: dict[str, Any]) -> dict[str, Any]:
    prev = prev or {}
    diff: dict[str, Any] = {}

    def diff_list(field: str) -> None:
        old = set(_normalize_list(prev.get(field)))
        new = set(_normalize_list(next_payload.get(field)))
        diff[field] = {
            "added": sorted(new - old),
            "removed": sorted(old - new),
        }

    for field in ("symbols", "keywords", "manual", "exclude"):
        if field in prev or field in next_payload:
            diff_list(field)
    return diff


def _resolve_project_config(session, project_id: int) -> dict[str, Any]:
    version = (
        session.query(ProjectVersion)
        .filter(
            ProjectVersion.project_id == project_id,
            ProjectVersion.description == PROJECT_CONFIG_TAG,
        )
        .order_by(ProjectVersion.created_at.desc())
        .first()
    )
    if version and version.content:
        try:
            payload = json.loads(version.content)
            if isinstance(payload, dict) and payload:
                return payload
        except json.JSONDecodeError:
            pass
    from app.routes import projects as project_routes

    return project_routes._load_default_config(session)


def _save_project_config(session, project_id: int, config: dict[str, Any]) -> ProjectVersion:
    content = json.dumps(config, ensure_ascii=False, indent=2)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version = ProjectVersion(
        project_id=project_id,
        version=datetime.utcnow().isoformat(),
        description=PROJECT_CONFIG_TAG,
        content=content,
        content_hash=content_hash,
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def _update_weights_and_categories(config: dict[str, Any]) -> None:
    themes = config.get("themes") or []
    weights: dict[str, float] = {}
    categories: list[dict[str, str]] = []
    for item in themes:
        key = str(item.get("key", "")).strip()
        if not key:
            continue
        weights[key] = float(item.get("weight") or 0.0)
        categories.append({"key": key, "label": item.get("label") or key})
    config["weights"] = weights
    config["categories"] = categories


def _upsert_system_theme_item(
    config: dict[str, Any],
    theme: SystemTheme,
    version: SystemThemeVersion,
    mode: str,
    weight: float | None,
) -> dict[str, Any]:
    payload = version.payload or {}
    system_base = _build_system_base(payload)
    themes = config.get("themes") or []
    target = None
    for item in themes:
        system_meta = item.get("system") or {}
        if system_meta.get("theme_id") == theme.id or item.get("key") == theme.key:
            target = item
            break
    if not target:
        target = {
            "key": payload.get("key") or theme.key,
            "label": system_base.get("label") or theme.label,
            "weight": float(weight or 0.0),
            "keywords": [],
            "manual": [],
            "exclude": [],
        }
        themes.append(target)
    target["label"] = system_base.get("label") or target.get("label") or theme.label
    if weight is not None:
        target["weight"] = float(weight)
    target["system"] = {
        "theme_id": theme.id,
        "version_id": version.id,
        "version": version.version,
        "source": theme.source,
        "mode": mode,
    }
    target["system_base"] = system_base
    target["keywords"] = []
    config["themes"] = themes
    _update_weights_and_categories(config)
    return config


@router.get("", response_model=SystemThemePageOut)
def list_system_themes(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        _ensure_system_themes(session)
        total = session.query(SystemTheme).count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        themes = (
            session.query(SystemTheme)
            .order_by(SystemTheme.key.asc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        items: list[SystemThemeOut] = []
        for theme in themes:
            latest = _get_latest_version(session, theme.id)
            items.append(
                SystemThemeOut(
                    id=theme.id,
                    key=theme.key,
                    label=theme.label,
                    source=theme.source,
                    description=theme.description,
                    latest_version_id=latest.id if latest else None,
                    latest_version=latest.version if latest else None,
                    updated_at=theme.updated_at,
                )
            )
        return SystemThemePageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/{theme_id}/versions", response_model=SystemThemeVersionPageOut)
def list_system_theme_versions(
    theme_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        theme = session.get(SystemTheme, theme_id)
        if not theme:
            raise HTTPException(status_code=404, detail="系统主题不存在")
        total = (
            session.query(SystemThemeVersion)
            .filter(SystemThemeVersion.theme_id == theme_id)
            .count()
        )
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        versions = (
            session.query(SystemThemeVersion)
            .filter(SystemThemeVersion.theme_id == theme_id)
            .order_by(SystemThemeVersion.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        items = [
            SystemThemeVersionOut(
                id=version.id,
                theme_id=version.theme_id,
                version=version.version,
                payload=version.payload or {},
                created_at=version.created_at,
            )
            for version in versions
        ]
        return SystemThemeVersionPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.post("/{theme_id}/refresh", response_model=SystemThemeRefreshOut)
def refresh_system_theme(theme_id: int):
    with get_session() as session:
        theme = session.get(SystemTheme, theme_id)
        if not theme:
            raise HTTPException(status_code=404, detail="系统主题不存在")
        latest = _get_latest_version(session, theme_id)
        next_payload: dict[str, Any] | None = None
        if theme.source == "config":
            for category in _load_theme_keywords():
                if str(category.get("key", "")).strip() == theme.key:
                    next_payload = _build_payload_from_category(category)
                    next_label = next_payload.get("label")
                    if next_label and next_label != theme.label:
                        theme.label = next_label
                    break
        elif theme.source == "membership":
            payloads = _load_sp500_payloads()
            next_payload = payloads.get(theme.key)
            if next_payload:
                next_label = next_payload.get("label")
                if next_label and next_label != theme.label:
                    theme.label = next_label
        elif theme.source == "data_complete":
            next_payload = _load_data_complete_payload()
            if next_payload:
                next_label = next_payload.get("label")
                if next_label and next_label != theme.label:
                    theme.label = next_label
        if not next_payload:
            raise HTTPException(status_code=400, detail="未找到可更新的数据来源")
        if latest and (latest.payload or {}) == next_payload:
            return SystemThemeRefreshOut(
                theme_id=theme.id,
                updated=False,
                version_id=latest.id,
                version=latest.version,
                affected_projects=0,
            )

        version = SystemThemeVersion(
            theme_id=theme.id,
            version=datetime.utcnow().isoformat(),
            payload=next_payload,
        )
        session.add(version)
        session.flush()
        theme.updated_at = datetime.utcnow()
        session.commit()

        diff = _diff_payload(latest.payload if latest else None, next_payload)
        affected_projects = 0
        bindings = (
            session.query(ProjectSystemThemeBinding)
            .filter(ProjectSystemThemeBinding.theme_id == theme.id)
            .all()
        )
        handled_projects: set[int] = set()
        for binding in bindings:
            if binding.mode != "follow_latest":
                continue
            handled_projects.add(binding.project_id)
            config = _resolve_project_config(session, binding.project_id)
            if not config:
                continue
            config = _upsert_system_theme_item(
                config=config,
                theme=theme,
                version=version,
                mode=binding.mode,
                weight=None,
            )
            project_version = _save_project_config(session, binding.project_id, config)
            binding.version_id = version.id
            binding.updated_at = datetime.utcnow()
            session.add(
                ThemeChangeReport(
                    project_id=binding.project_id,
                    theme_id=theme.id,
                    from_version_id=latest.id if latest else None,
                    to_version_id=version.id,
                    diff=diff,
                )
            )
            record_audit(
                session,
                action="system_theme.refresh",
                resource_type="project",
                resource_id=binding.project_id,
                detail={
                    "theme_id": theme.id,
                    "from_version_id": latest.id if latest else None,
                    "to_version_id": version.id,
                    "project_version_id": project_version.id,
                },
            )
            session.commit()
            affected_projects += 1

        projects = session.query(Project).all()
        for project in projects:
            if project.id in handled_projects:
                continue
            config = _resolve_project_config(session, project.id)
            themes = config.get("themes") or []
            matched = False
            for item in themes:
                system_meta = item.get("system") or {}
                if system_meta.get("theme_id") == theme.id and system_meta.get("mode") == "follow_latest":
                    matched = True
                    break
            if not matched:
                continue
            config = _upsert_system_theme_item(
                config=config,
                theme=theme,
                version=version,
                mode="follow_latest",
                weight=None,
            )
            project_version = _save_project_config(session, project.id, config)
            binding = ProjectSystemThemeBinding(
                project_id=project.id,
                theme_id=theme.id,
                version_id=version.id,
                mode="follow_latest",
            )
            session.add(binding)
            session.add(
                ThemeChangeReport(
                    project_id=project.id,
                    theme_id=theme.id,
                    from_version_id=latest.id if latest else None,
                    to_version_id=version.id,
                    diff=diff,
                )
            )
            record_audit(
                session,
                action="system_theme.refresh",
                resource_type="project",
                resource_id=project.id,
                detail={
                    "theme_id": theme.id,
                    "from_version_id": latest.id if latest else None,
                    "to_version_id": version.id,
                    "project_version_id": project_version.id,
                },
            )
            session.commit()
            affected_projects += 1

        return SystemThemeRefreshOut(
            theme_id=theme.id,
            updated=True,
            version_id=version.id,
            version=version.version,
            affected_projects=affected_projects,
        )


@router.post("/projects/{project_id}/import", response_model=SystemThemeImportOut)
def import_system_theme(project_id: int, payload: SystemThemeImportRequest):
    mode = payload.mode or "follow_latest"
    if mode not in {"follow_latest", "pin_version", "snapshot"}:
        raise HTTPException(status_code=400, detail="导入模式不支持")
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        theme = session.get(SystemTheme, payload.theme_id)
        if not theme:
            raise HTTPException(status_code=404, detail="系统主题不存在")
        version = None
        if payload.version_id:
            version = session.get(SystemThemeVersion, payload.version_id)
            if not version or version.theme_id != theme.id:
                raise HTTPException(status_code=400, detail="系统主题版本无效")
        if not version:
            version = _get_latest_version(session, theme.id)
        if not version:
            raise HTTPException(status_code=400, detail="系统主题尚无版本")

        config = _resolve_project_config(session, project_id)
        if mode == "snapshot":
            snapshot = _build_system_base(version.payload or {})
            themes = config.get("themes") or []
            existing_keys = {str(item.get("key", "")).strip() for item in themes}
            theme_key = theme.key
            if theme_key in existing_keys:
                theme_key = f"{theme.key}_SNAPSHOT_{version.id}"
            theme_item = {
                "key": theme_key,
                "label": snapshot.get("label") or theme.label,
                "weight": float(payload.weight or 0.0),
                "keywords": snapshot.get("keywords") or [],
                "manual": snapshot.get("manual") or [],
                "exclude": snapshot.get("exclude") or [],
                "source": "snapshot",
                "snapshot": {
                    "theme_id": theme.id,
                    "version_id": version.id,
                    "version": version.version,
                },
            }
            themes.append(theme_item)
            config["themes"] = themes
            _update_weights_and_categories(config)
            project_version = _save_project_config(session, project_id, config)
            record_audit(
                session,
                action="system_theme.import_snapshot",
                resource_type="project",
                resource_id=project_id,
                detail={"theme_id": theme.id, "version_id": version.id},
            )
            session.commit()
            return SystemThemeImportOut(
                project_id=project_id,
                theme_id=theme.id,
                mode=mode,
                version_id=version.id,
                project_version_id=project_version.id,
            )

        config = _upsert_system_theme_item(
            config=config,
            theme=theme,
            version=version,
            mode=mode,
            weight=payload.weight,
        )
        binding = (
            session.query(ProjectSystemThemeBinding)
            .filter(
                ProjectSystemThemeBinding.project_id == project_id,
                ProjectSystemThemeBinding.theme_id == theme.id,
            )
            .first()
        )
        if not binding:
            binding = ProjectSystemThemeBinding(
                project_id=project_id,
                theme_id=theme.id,
                version_id=version.id,
                mode=mode,
            )
            session.add(binding)
        else:
            binding.version_id = version.id
            binding.mode = mode
        project_version = _save_project_config(session, project_id, config)
        record_audit(
            session,
            action="system_theme.import",
            resource_type="project",
            resource_id=project_id,
            detail={"theme_id": theme.id, "version_id": version.id, "mode": mode},
        )
        session.commit()
        return SystemThemeImportOut(
            project_id=project_id,
            theme_id=theme.id,
            mode=mode,
            version_id=version.id,
            project_version_id=project_version.id,
        )


@router.get("/projects/{project_id}/reports/page", response_model=ThemeChangeReportPageOut)
def list_theme_change_reports(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        total = (
            session.query(ThemeChangeReport)
            .filter(ThemeChangeReport.project_id == project_id)
            .count()
        )
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        reports = (
            session.query(ThemeChangeReport)
            .filter(ThemeChangeReport.project_id == project_id)
            .order_by(ThemeChangeReport.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        items = [
            ThemeChangeReportOut(
                id=report.id,
                project_id=report.project_id,
                theme_id=report.theme_id,
                from_version_id=report.from_version_id,
                to_version_id=report.to_version_id,
                diff=report.diff or {},
                created_at=report.created_at,
            )
            for report in reports
        ]
        return ThemeChangeReportPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )
