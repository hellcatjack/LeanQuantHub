from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.db import engine, get_session
from app.models import Base
from app.routes import (
    algorithms,
    automation,
    audit_logs,
    backtests,
    datasets,
    decisions,
    factor_scores,
    ml,
    ml_pipelines,
    pit,
    pretrade,
    projects,
    reports,
    system_themes,
    universe,
)

app = FastAPI(title="StockLean Platform API")
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_utf8_json_charset(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset" not in content_type:
        response.headers["content-type"] = f"{content_type}; charset=utf-8"
    return response


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        with get_session() as session:
            system_themes._ensure_system_themes(session)
    except Exception:
        logger.exception("Failed to ensure system themes on startup")
    datasets.resume_bulk_sync_jobs()


app.include_router(projects.router)
app.include_router(algorithms.router)
app.include_router(backtests.router)
app.include_router(reports.router)
app.include_router(datasets.router)
app.include_router(audit_logs.router)
app.include_router(automation.router)
app.include_router(decisions.router)
app.include_router(system_themes.router)
app.include_router(universe.router)
app.include_router(ml.router)
app.include_router(ml_pipelines.router)
app.include_router(pit.router)
app.include_router(pretrade.router)
app.include_router(factor_scores.router)
