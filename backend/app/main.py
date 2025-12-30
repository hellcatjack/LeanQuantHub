from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import engine
from app.models import Base
from app.routes import algorithms, audit_logs, backtests, datasets, projects, reports

app = FastAPI(title="StockLean Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


app.include_router(projects.router)
app.include_router(algorithms.router)
app.include_router(backtests.router)
app.include_router(reports.router)
app.include_router(datasets.router)
app.include_router(audit_logs.router)
