from __future__ import annotations

from datetime import datetime
import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.db import get_session
from app.models import (
    PreTradeRun,
    PreTradeSettings,
    PreTradeStep,
    PreTradeTemplate,
    Project,
)
from app.schemas import (
    PreTradeRunCreate,
    PreTradeRunDetail,
    PreTradeRunOut,
    PreTradeRunPageOut,
    PreTradeSettingsOut,
    PreTradeSettingsUpdate,
    PreTradeSummaryOut,
    PreTradeStepOut,
    PreTradeTelegramTest,
    PreTradeTelegramTestOut,
    PreTradeTemplateCreate,
    PreTradeTemplateOut,
    PreTradeTemplateUpdate,
)
from app.services.audit_log import record_audit
from app.services.pretrade_runner import (
    PRETRADE_ACTIVE_STATUSES,
    _compute_deadline_at,
    _create_steps,
    _get_or_create_settings,
    _notify_telegram,
    run_pretrade_run,
)

router = APIRouter(prefix="/api/pretrade", tags=["pretrade"])

MAX_PAGE_SIZE = 200


def _coerce_pagination(page: int, page_size: int, total: int) -> tuple[int, int, int]:
    safe_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    total_pages = max(1, math.ceil(total / safe_page_size)) if total else 1
    safe_page = min(max(page, 1), total_pages)
    offset = (safe_page - 1) * safe_page_size
    return safe_page, safe_page_size, offset


def _mask_token(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}***{value[-3:]}"


@router.get("/settings", response_model=PreTradeSettingsOut)
def get_pretrade_settings():
    with get_session() as session:
        settings = _get_or_create_settings(session)
        out = PreTradeSettingsOut.model_validate(settings, from_attributes=True)
        out.telegram_bot_token = _mask_token(out.telegram_bot_token)
        out.telegram_chat_id = _mask_token(out.telegram_chat_id)
        return out


@router.post("/settings", response_model=PreTradeSettingsOut)
def update_pretrade_settings(payload: PreTradeSettingsUpdate):
    with get_session() as session:
        settings = _get_or_create_settings(session)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            if key == "telegram_bot_token" and value == "":
                value = None
            if key == "telegram_chat_id" and value == "":
                value = None
            setattr(settings, key, value)
        session.commit()
        session.refresh(settings)
        out = PreTradeSettingsOut.model_validate(settings, from_attributes=True)
        out.telegram_bot_token = _mask_token(out.telegram_bot_token)
        out.telegram_chat_id = _mask_token(out.telegram_chat_id)
        return out


@router.post("/settings/telegram-test", response_model=PreTradeTelegramTestOut)
def test_pretrade_telegram(payload: PreTradeTelegramTest):
    with get_session() as session:
        settings = _get_or_create_settings(session)
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise HTTPException(status_code=400, detail="Telegram 未配置")
        message = payload.message or "PreTrade checklist test"
        _notify_telegram(settings, message)
        return PreTradeTelegramTestOut(ok=True)


@router.get("/templates", response_model=list[PreTradeTemplateOut])
def list_pretrade_templates(project_id: int | None = Query(None)):
    with get_session() as session:
        query = session.query(PreTradeTemplate).order_by(PreTradeTemplate.created_at.desc())
        if project_id is not None:
            query = query.filter(PreTradeTemplate.project_id == project_id)
        return query.all()


@router.post("/templates", response_model=PreTradeTemplateOut)
def create_pretrade_template(payload: PreTradeTemplateCreate):
    with get_session() as session:
        template = PreTradeTemplate(
            project_id=payload.project_id,
            name=payload.name,
            params=payload.params,
            is_active=payload.is_active,
        )
        session.add(template)
        session.commit()
        session.refresh(template)
        record_audit(
            session,
            action="pretrade.template.create",
            resource_type="pretrade_template",
            resource_id=template.id,
            detail={"project_id": payload.project_id, "name": payload.name},
        )
        session.commit()
        return template


@router.post("/templates/{template_id}", response_model=PreTradeTemplateOut)
def update_pretrade_template(template_id: int, payload: PreTradeTemplateUpdate):
    with get_session() as session:
        template = session.get(PreTradeTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="template not found")
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(template, key, value)
        session.commit()
        session.refresh(template)
        record_audit(
            session,
            action="pretrade.template.update",
            resource_type="pretrade_template",
            resource_id=template.id,
            detail={"name": template.name},
        )
        session.commit()
        return template


@router.delete("/templates/{template_id}", response_model=PreTradeTemplateOut)
def delete_pretrade_template(template_id: int):
    with get_session() as session:
        template = session.get(PreTradeTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="template not found")
        if template.is_active:
            template.is_active = False
        settings = session.query(PreTradeSettings).first()
        if settings and settings.current_template_id == template_id:
            settings.current_template_id = None
        template_out = PreTradeTemplateOut.model_validate(template, from_attributes=True)
        session.delete(template)
        record_audit(
            session,
            action="pretrade.template.delete",
            resource_type="pretrade_template",
            resource_id=template_id,
            detail={"name": template_out.name},
        )
        session.commit()
        return template_out


@router.post("/templates/{template_id}/activate", response_model=PreTradeTemplateOut)
def activate_pretrade_template(template_id: int):
    with get_session() as session:
        template = session.get(PreTradeTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="template not found")
        session.query(PreTradeTemplate).update({"is_active": False})
        template.is_active = True
        settings = _get_or_create_settings(session)
        settings.current_template_id = template.id
        session.commit()
        session.refresh(template)
        record_audit(
            session,
            action="pretrade.template.activate",
            resource_type="pretrade_template",
            resource_id=template.id,
            detail={"name": template.name},
        )
        session.commit()
        return template


@router.get("/runs", response_model=list[PreTradeRunOut])
def list_pretrade_runs(
    project_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    with get_session() as session:
        query = session.query(PreTradeRun).order_by(PreTradeRun.created_at.desc())
        if project_id is not None:
            query = query.filter(PreTradeRun.project_id == project_id)
        return query.offset(offset).limit(limit).all()


@router.get("/runs/page", response_model=PreTradeRunPageOut)
def list_pretrade_runs_page(
    project_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
):
    with get_session() as session:
        query = session.query(PreTradeRun)
        if project_id is not None:
            query = query.filter(PreTradeRun.project_id == project_id)
        total = query.count()
        safe_page, safe_page_size, offset = _coerce_pagination(page, page_size, total)
        items = (
            query.order_by(PreTradeRun.created_at.desc())
            .offset(offset)
            .limit(safe_page_size)
            .all()
        )
        return PreTradeRunPageOut(
            items=items,
            total=total,
            page=safe_page,
            page_size=safe_page_size,
        )


@router.get("/summary", response_model=PreTradeSummaryOut)
def get_pretrade_summary(project_id: int | None = Query(None)):
    with get_session() as session:
        query = session.query(PreTradeRun)
        if project_id is not None:
            query = query.filter(PreTradeRun.project_id == project_id)
        active = (
            query.filter(PreTradeRun.status.in_(PRETRADE_ACTIVE_STATUSES))
            .order_by(PreTradeRun.created_at.desc())
            .first()
        )
        run = active or query.order_by(PreTradeRun.created_at.desc()).first()
        if not run:
            return PreTradeSummaryOut(
                run=None,
                steps_total=0,
                steps_success=0,
                steps_failed=0,
                steps_running=0,
                steps_queued=0,
                steps_skipped=0,
                progress=0.0,
            )
        steps = session.query(PreTradeStep).filter(PreTradeStep.run_id == run.id).all()
        total = len(steps)
        success = sum(1 for step in steps if step.status == "success")
        failed = sum(1 for step in steps if step.status == "failed")
        running = sum(1 for step in steps if step.status == "running")
        queued = sum(1 for step in steps if step.status == "queued")
        skipped = sum(1 for step in steps if step.status == "skipped")
        done = success + skipped
        progress = (done / total) if total else 0.0
        return PreTradeSummaryOut(
            run=PreTradeRunOut.model_validate(run, from_attributes=True),
            steps_total=total,
            steps_success=success,
            steps_failed=failed,
            steps_running=running,
            steps_queued=queued,
            steps_skipped=skipped,
            progress=progress,
        )


@router.get("/runs/{run_id}", response_model=PreTradeRunDetail)
def get_pretrade_run(run_id: int):
    with get_session() as session:
        run = session.get(PreTradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        steps = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run_id)
            .order_by(PreTradeStep.step_order.asc())
            .all()
        )
        return PreTradeRunDetail(
            run=PreTradeRunOut.model_validate(run, from_attributes=True),
            steps=[PreTradeStepOut.model_validate(step, from_attributes=True) for step in steps],
        )


@router.post("/runs", response_model=PreTradeRunOut)
def create_pretrade_run(payload: PreTradeRunCreate, background_tasks: BackgroundTasks):
    with get_session() as session:
        project = session.get(Project, payload.project_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        active = (
            session.query(PreTradeRun)
            .filter(PreTradeRun.status.in_(PRETRADE_ACTIVE_STATUSES))
            .first()
        )
        if active:
            raise HTTPException(status_code=409, detail="已有运行中的 checklist")
        settings = _get_or_create_settings(session)
        template_id = payload.template_id or settings.current_template_id
        template = session.get(PreTradeTemplate, template_id) if template_id else None
        run = PreTradeRun(
            project_id=payload.project_id,
            template_id=template.id if template else None,
            status="queued",
            window_start=payload.window_start,
            window_end=payload.window_end,
            deadline_at=payload.deadline_at,
            params=payload.params,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _create_steps(session, run, template)
        run.deadline_at = run.deadline_at or _compute_deadline_at(run, settings)
        session.commit()
        record_audit(
            session,
            action="pretrade.run.create",
            resource_type="pretrade_run",
            resource_id=run.id,
            detail={"project_id": payload.project_id},
        )
        session.commit()
    background_tasks.add_task(run_pretrade_run, run.id, None)
    return run


@router.post("/runs/{run_id}/cancel", response_model=PreTradeRunOut)
def cancel_pretrade_run(run_id: int):
    with get_session() as session:
        run = session.get(PreTradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status in {"success", "failed", "canceled"}:
            return run
        run.status = "cancel_requested"
        run.updated_at = datetime.utcnow()
        session.commit()
        return run


@router.post("/runs/{run_id}/resume", response_model=PreTradeRunOut)
def resume_pretrade_run(run_id: int, background_tasks: BackgroundTasks):
    with get_session() as session:
        run = session.get(PreTradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status in {"success", "running"}:
            return run
        step = (
            session.query(PreTradeStep)
            .filter(PreTradeStep.run_id == run_id, PreTradeStep.status == "failed")
            .order_by(PreTradeStep.step_order.asc())
            .first()
        )
        if not step:
            raise HTTPException(status_code=400, detail="没有可重试的步骤")
        step.status = "queued"
        step.retry_count = 0
        step.next_retry_at = None
        step.message = None
        step.updated_at = datetime.utcnow()
        run.status = "queued"
        session.commit()
        background_tasks.add_task(run_pretrade_run, run.id, step.id)
        return run


@router.post("/runs/{run_id}/steps/{step_id}/retry", response_model=PreTradeRunOut)
def retry_pretrade_step(
    run_id: int, step_id: int, background_tasks: BackgroundTasks
):
    with get_session() as session:
        run = session.get(PreTradeRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        step = session.get(PreTradeStep, step_id)
        if not step or step.run_id != run_id:
            raise HTTPException(status_code=404, detail="step not found")
        step.status = "queued"
        step.retry_count = 0
        step.next_retry_at = None
        step.message = None
        step.updated_at = datetime.utcnow()
        run.status = "queued"
        session.commit()
        background_tasks.add_task(run_pretrade_run, run.id, step.id)
        return run
