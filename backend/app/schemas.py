from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectVersionCreate(BaseModel):
    version: str | None = None
    description: str | None = None
    content: str | None = None


class ProjectVersionOut(BaseModel):
    id: int
    project_id: int
    version: str | None
    description: str | None
    content_hash: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectDiffOut(BaseModel):
    project_id: int
    from_version_id: int
    to_version_id: int
    diff: str


class ProjectPageOut(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    page_size: int


class ProjectVersionPageOut(BaseModel):
    items: list[ProjectVersionOut]
    total: int
    page: int
    page_size: int


class ProjectAlgorithmBindCreate(BaseModel):
    algorithm_id: int
    algorithm_version_id: int
    is_locked: bool = True


class ProjectAlgorithmBindOut(BaseModel):
    project_id: int
    exists: bool
    algorithm_id: int | None = None
    algorithm_version_id: int | None = None
    algorithm_name: str | None = None
    algorithm_version: str | None = None
    is_locked: bool = False
    updated_at: datetime | None = None


class ProjectConfigCreate(BaseModel):
    config: dict[str, Any]
    version: str | None = None


class ProjectConfigOut(BaseModel):
    project_id: int
    config: dict[str, Any]
    source: str
    updated_at: str | None = None
    version_id: int | None = None


class ProjectDataStatusOut(BaseModel):
    project_id: int
    data_root: str
    membership: dict[str, Any]
    universe: dict[str, Any]
    themes: dict[str, Any]
    metrics: dict[str, Any]
    prices: dict[str, Any]
    backtest: dict[str, Any]


class ThemeSummaryItem(BaseModel):
    key: str
    label: str
    symbols: int
    sample: list[str]
    manual_symbols: list[str] = []


class ProjectThemeSummaryOut(BaseModel):
    project_id: int
    updated_at: str | None = None
    total_symbols: int
    themes: list[ThemeSummaryItem]


class ProjectThemeSymbolsOut(BaseModel):
    project_id: int
    category: str
    label: str | None = None
    symbols: list[str]
    manual_symbols: list[str] = []


class ThemeSearchItem(BaseModel):
    key: str
    label: str
    is_manual: bool = False


class ProjectThemeSearchOut(BaseModel):
    project_id: int
    symbol: str
    themes: list[ThemeSearchItem]


class ProjectDataRefreshRequest(BaseModel):
    steps: list[str] | None = None


class ProjectDataRefreshOut(BaseModel):
    project_id: int
    steps: list[str]
    status: str


class ProjectThematicBacktestOut(BaseModel):
    project_id: int
    status: str
    summary: dict[str, Any] | None = None
    updated_at: str | None = None
    source: str | None = None


class BacktestCreate(BaseModel):
    project_id: int
    algorithm_version_id: int | None = None
    params: dict[str, Any] | None = None


class BacktestOut(BaseModel):
    id: int
    project_id: int
    status: str
    params: dict[str, Any] | None
    metrics: dict[str, Any] | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class BacktestListOut(BacktestOut):
    report_id: int | None = None


class BacktestPageOut(BaseModel):
    items: list[BacktestListOut]
    total: int
    page: int
    page_size: int


class BacktestCompareRequest(BaseModel):
    run_ids: list[int]


class BacktestCompareItem(BaseModel):
    id: int
    project_id: int
    project_name: str | None
    status: str
    metrics: dict[str, Any] | None
    created_at: datetime
    ended_at: datetime | None

    class Config:
        from_attributes = True


class ReportOut(BaseModel):
    id: int
    run_id: int
    report_type: str
    path: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReportPageOut(BaseModel):
    items: list[ReportOut]
    total: int
    page: int
    page_size: int


class DatasetOut(BaseModel):
    id: int
    name: str
    vendor: str | None
    asset_class: str | None
    region: str | None
    frequency: str | None
    coverage_start: str | None
    coverage_end: str | None
    source_path: str | None
    updated_at: datetime

    class Config:
        from_attributes = True


class DatasetPageOut(BaseModel):
    items: list[DatasetOut]
    total: int
    page: int
    page_size: int


class DatasetCreate(BaseModel):
    name: str
    vendor: str | None = None
    asset_class: str | None = None
    region: str | None = None
    frequency: str | None = None
    coverage_start: str | None = None
    coverage_end: str | None = None
    source_path: str | None = None


class DatasetUpdate(BaseModel):
    name: str | None = None
    vendor: str | None = None
    asset_class: str | None = None
    region: str | None = None
    frequency: str | None = None
    coverage_start: str | None = None
    coverage_end: str | None = None
    source_path: str | None = None


class DatasetQualityOut(BaseModel):
    dataset_id: int
    frequency: str | None
    coverage_start: str | None
    coverage_end: str | None
    coverage_days: int | None
    expected_points_estimate: int | None
    issues: list[str]
    status: str


class DatasetQualityScanRequest(BaseModel):
    file_path: str
    date_column: str = "date"
    close_column: str = "close"
    frequency: str | None = None


class DatasetQualityScanOut(BaseModel):
    dataset_id: int
    file_path: str
    rows: int
    coverage_start: str | None
    coverage_end: str | None
    missing_days: int | None
    missing_ratio: float | None
    null_close_rows: int
    duplicate_timestamps: int
    outlier_returns: int
    max_abs_return: float | None
    issues: list[str]


class DatasetDeleteRequest(BaseModel):
    dataset_ids: list[int]


class DatasetDeleteOut(BaseModel):
    deleted_ids: list[int]
    missing_ids: list[int]
    deleted_files: list[str]


class DatasetFetchRequest(BaseModel):
    symbol: str
    vendor: str | None = "stooq"
    asset_class: str | None = "Equity"
    region: str | None = "US"
    frequency: str | None = "daily"
    name: str | None = None
    auto_sync: bool = True


class DatasetFetchOut(BaseModel):
    dataset: DatasetOut
    job: DataSyncOut | None = None
    created: bool


class DataSyncCreate(BaseModel):
    source_path: str | None = None
    date_column: str = "date"


class DataSyncOut(BaseModel):
    id: int
    dataset_id: int
    dataset_name: str | None = None
    source_path: str
    date_column: str
    status: str
    rows_scanned: int | None
    coverage_start: str | None
    coverage_end: str | None
    normalized_path: str | None
    output_path: str | None
    snapshot_path: str | None
    lean_path: str | None
    adjusted_path: str | None
    lean_adjusted_path: str | None
    message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    class Config:
        from_attributes = True


class DataSyncPageOut(BaseModel):
    items: list[DataSyncOut]
    total: int
    page: int
    page_size: int


class AuditLogOut(BaseModel):
    id: int
    actor: str
    action: str
    resource_type: str
    resource_id: int | None
    detail: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogPageOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int


class AlgorithmCreate(BaseModel):
    name: str
    description: str | None = None
    language: str = "Python"
    file_path: str | None = None
    type_name: str | None = None
    version: str | None = None


class AlgorithmOut(BaseModel):
    id: int
    name: str
    description: str | None
    language: str
    file_path: str | None
    type_name: str | None
    version: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AlgorithmVersionCreate(BaseModel):
    version: str | None = None
    description: str | None = None
    language: str | None = None
    file_path: str | None = None
    type_name: str | None = None
    content: str | None = None


class AlgorithmVersionOut(BaseModel):
    id: int
    algorithm_id: int
    version: str | None
    description: str | None
    language: str
    file_path: str | None
    type_name: str | None
    content_hash: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AlgorithmPageOut(BaseModel):
    items: list[AlgorithmOut]
    total: int
    page: int
    page_size: int


class AlgorithmVersionPageOut(BaseModel):
    items: list[AlgorithmVersionOut]
    total: int
    page: int
    page_size: int


class AlgorithmDiffOut(BaseModel):
    algorithm_id: int
    from_version_id: int
    to_version_id: int
    diff: str


class AlgorithmProjectCreate(BaseModel):
    name: str
    description: str | None = None
    lock_version: bool = True
