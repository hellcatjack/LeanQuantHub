from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Float, JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, BigInteger
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    backtests: Mapped[list["BacktestRun"]] = relationship(back_populates="project")
    versions: Mapped[list["ProjectVersion"]] = relationship(back_populates="project")
    algorithm_binding: Mapped["ProjectAlgorithmBinding | None"] = relationship(
        back_populates="project", uselist=False
    )
    ml_train_jobs: Mapped[list["MLTrainJob"]] = relationship(back_populates="project")
    ml_pipelines: Mapped[list["MLPipelineRun"]] = relationship(back_populates="project")
    decision_snapshots: Mapped[list["DecisionSnapshot"]] = relationship(
        back_populates="project"
    )
    factor_score_jobs: Mapped[list["FactorScoreJob"]] = relationship(
        back_populates="project"
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    pipeline_id: Mapped[int | None] = mapped_column(
        ForeignKey("ml_pipeline_runs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="backtests")
    pipeline: Mapped["MLPipelineRun | None"] = relationship(back_populates="backtests")
    reports: Mapped[list["Report"]] = relationship(back_populates="run")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), default="summary")
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped[BacktestRun] = relationship(back_populates="reports")


class MLTrainJob(Base):
    __tablename__ = "ml_train_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    pipeline_id: Mapped[int | None] = mapped_column(
        ForeignKey("ml_pipeline_runs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued")
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scores_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="ml_train_jobs")
    pipeline: Mapped["MLPipelineRun | None"] = relationship(back_populates="train_jobs")


class MLPipelineRun(Base):
    __tablename__ = "ml_pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="ml_pipelines")
    train_jobs: Mapped[list["MLTrainJob"]] = relationship(back_populates="pipeline")
    backtests: Mapped[list["BacktestRun"]] = relationship(back_populates="pipeline")


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    pipeline_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    train_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    snapshot_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    items_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filters_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="decision_snapshots")


class FactorScoreJob(Base):
    __tablename__ = "factor_score_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scores_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="factor_score_jobs")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32), nullable=True)
    region: Mapped[str] = mapped_column(String(32), nullable=True)
    frequency: Mapped[str] = mapped_column(String(16), nullable=True)
    coverage_start: Mapped[str] = mapped_column(String(16), nullable=True)
    coverage_end: Mapped[str] = mapped_column(String(16), nullable=True)
    source_path: Mapped[str] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    sync_jobs: Mapped[list["DataSyncJob"]] = relationship(back_populates="dataset")


class ProjectVersion(Base):
    __tablename__ = "project_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql"), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="versions")


class Algorithm(Base):
    __tablename__ = "algorithms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="Python")
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    versions: Mapped[list["AlgorithmVersion"]] = relationship(back_populates="algorithm")
    project_bindings: Mapped[list["ProjectAlgorithmBinding"]] = relationship(
        back_populates="algorithm"
    )


class AlgorithmVersion(Base):
    __tablename__ = "algorithm_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    algorithm_id: Mapped[int] = mapped_column(ForeignKey("algorithms.id"), nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="Python")
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    type_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    algorithm: Mapped[Algorithm] = relationship(back_populates="versions")
    project_bindings: Mapped[list["ProjectAlgorithmBinding"]] = relationship(
        back_populates="algorithm_version"
    )


class ProjectAlgorithmBinding(Base):
    __tablename__ = "project_algorithm_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, unique=True
    )
    algorithm_id: Mapped[int] = mapped_column(ForeignKey("algorithms.id"), nullable=False)
    algorithm_version_id: Mapped[int] = mapped_column(
        ForeignKey("algorithm_versions.id"), nullable=False
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    project: Mapped[Project] = relationship(back_populates="algorithm_binding")
    algorithm: Mapped[Algorithm] = relationship(back_populates="project_bindings")
    algorithm_version: Mapped[AlgorithmVersion] = relationship(
        back_populates="project_bindings"
    )


class SystemTheme(Base):
    __tablename__ = "system_themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="config")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    versions: Mapped[list["SystemThemeVersion"]] = relationship(back_populates="theme")
    bindings: Mapped[list["ProjectSystemThemeBinding"]] = relationship(
        back_populates="theme"
    )


class SystemThemeVersion(Base):
    __tablename__ = "system_theme_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theme_id: Mapped[int] = mapped_column(ForeignKey("system_themes.id"), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    theme: Mapped["SystemTheme"] = relationship(back_populates="versions")
    bindings: Mapped[list["ProjectSystemThemeBinding"]] = relationship(
        back_populates="version"
    )


class ProjectSystemThemeBinding(Base):
    __tablename__ = "project_system_theme_bindings"
    __table_args__ = (UniqueConstraint("project_id", "theme_id", name="uq_project_theme"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    theme_id: Mapped[int] = mapped_column(ForeignKey("system_themes.id"), nullable=False)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("system_theme_versions.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(32), default="follow_latest")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    theme: Mapped["SystemTheme"] = relationship(back_populates="bindings")
    version: Mapped["SystemThemeVersion"] = relationship(back_populates="bindings")


class ThemeChangeReport(Base):
    __tablename__ = "theme_change_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    theme_id: Mapped[int] = mapped_column(ForeignKey("system_themes.id"), nullable=False)
    from_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("system_theme_versions.id"), nullable=True
    )
    to_version_id: Mapped[int] = mapped_column(
        ForeignKey("system_theme_versions.id"), nullable=False
    )
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UniverseMembership(Base):
    __tablename__ = "universe_memberships"
    __table_args__ = (
        UniqueConstraint("symbol", "category", name="uq_universe_symbol_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(16), nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    in_sp500_history: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    theme_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    theme_keyword: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

class DataSyncJob(Base):
    __tablename__ = "data_sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    source_path: Mapped[str] = mapped_column(String(255), nullable=False)
    date_column: Mapped[str] = mapped_column(String(64), default="date")
    reset_history: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    rows_scanned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_start: Mapped[str | None] = mapped_column(String(16), nullable=True)
    coverage_end: Mapped[str | None] = mapped_column(String(16), nullable=True)
    normalized_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lean_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adjusted_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lean_adjusted_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    dataset: Mapped[Dataset] = relationship(back_populates="sync_jobs")


class BulkSyncJob(Base):
    __tablename__ = "bulk_sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    phase: Mapped[str] = mapped_column(String(32), default="listing_refresh")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    total_symbols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_symbols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_datasets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reused_datasets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queued_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offset: Mapped[int] = mapped_column(Integer, default=0)
    batch_size: Mapped[int] = mapped_column(Integer, default=200)
    enqueued_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enqueued_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queue_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    queue_ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PitWeeklyJob(Base):
    __tablename__ = "pit_weekly_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PitFundamentalJob(Base):
    __tablename__ = "pit_fundamental_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AutoWeeklyJob(Base):
    __tablename__ = "auto_weekly_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pit_weekly_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pit_weekly_log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pit_fundamental_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pit_fundamental_log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backtest_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backtest_log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backtest_output_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backtest_artifact_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PreTradeTemplate(Base):
    __tablename__ = "pretrade_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PreTradeSettings(Base):
    __tablename__ = "pretrade_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    current_template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_bot_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    retry_base_delay_seconds: Mapped[int] = mapped_column(Integer, default=60)
    retry_max_delay_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    deadline_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deadline_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_project_only: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_decision_snapshot: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PreTradeRun(Base):
    __tablename__ = "pretrade_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PreTradeStep(Base):
    __tablename__ = "pretrade_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pretrade_runs.id"), nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[float | None] = mapped_column(nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifacts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class IBSettings(Base):
    __tablename__ = "ib_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(128), default="127.0.0.1")
    port: Mapped[int] = mapped_column(Integer, default=7497)
    client_id: Mapped[int] = mapped_column(Integer, default=1)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    market_data_type: Mapped[str] = mapped_column(String(16), default="realtime")
    api_mode: Mapped[str] = mapped_column(String(16), default="ib")
    use_regulatory_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TradeSettings(Base):
    __tablename__ = "trade_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    risk_defaults: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_data_source: Mapped[str] = mapped_column(String(16), default="ib")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TradeGuardState(Base):
    __tablename__ = "trade_guard_state"
    __table_args__ = (
        UniqueConstraint("project_id", "trade_date", "mode", name="uq_trade_guard_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    status: Mapped[str] = mapped_column(String(16), default="active")
    halt_reason: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_triggers: Mapped[int] = mapped_column(Integer, default=0)
    order_failures: Mapped[int] = mapped_column(Integer, default=0)
    market_data_errors: Mapped[int] = mapped_column(Integer, default=0)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_valuation_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valuation_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class IBConnectionState(Base):
    __tablename__ = "ib_connection_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    degraded_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class IBContractCache(Base):
    __tablename__ = "ib_contract_cache"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "sec_type",
            "exchange",
            "currency",
            name="uq_ib_contract_cache",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    sec_type: Mapped[str] = mapped_column(String(16), default="STK")
    exchange: Mapped[str] = mapped_column(String(32), default="SMART")
    primary_exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    con_id: Mapped[int] = mapped_column(Integer, nullable=False)
    local_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    multiplier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class IBHistoryJob(Base):
    __tablename__ = "ib_history_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_symbols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_symbols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success_symbols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_symbols: Mapped[int | None] = mapped_column(Integer, nullable=True)
    log_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TradeRun(Base):
    __tablename__ = "trade_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    decision_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TradeOrder(Base):
    __tablename__ = "trade_orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_trade_order_client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("trade_runs.id"), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), default="MKT")
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="NEW")
    filled_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ib_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ib_perm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_status_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TradeFill(Base):
    __tablename__ = "trade_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("trade_orders.id"), nullable=False)
    fill_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
