from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    backtests: Mapped[list["BacktestRun"]] = relationship(back_populates="project")
    versions: Mapped[list["ProjectVersion"]] = relationship(back_populates="project")
    algorithm_binding: Mapped["ProjectAlgorithmBinding | None"] = relationship(
        back_populates="project", uselist=False
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="backtests")
    reports: Mapped[list["Report"]] = relationship(back_populates="run")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), default="summary")
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped[BacktestRun] = relationship(back_populates="reports")


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
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
