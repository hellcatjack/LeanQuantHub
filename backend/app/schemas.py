from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None
    is_archived: bool = False
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
    sample_types: dict[str, str] = {}
    manual_symbols: list[str] = []
    exclude_symbols: list[str] = []


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
    auto_symbols: list[str] = []
    manual_symbols: list[str] = []
    exclude_symbols: list[str] = []
    symbol_types: dict[str, str] = {}


class ThemeSearchItem(BaseModel):
    key: str
    label: str
    is_manual: bool = False
    is_excluded: bool = False


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
    pipeline_id: int | None = None


class BacktestOut(BaseModel):
    id: int
    project_id: int
    pipeline_id: int | None = None
    status: str
    params: dict[str, Any] | None
    metrics: dict[str, Any] | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class BacktestProgressOut(BaseModel):
    run_id: int
    status: str | None = None
    progress: float | None = None
    as_of: str | None = None


class MLTrainCreate(BaseModel):
    project_id: int
    device: str = "auto"
    train_years: int | None = None
    valid_months: int | None = None
    test_months: int | None = None
    step_months: int | None = None
    label_horizon_days: int | None = None
    train_start_year: int | None = None
    model_type: str | None = None
    model_params: dict[str, Any] | None = None
    sample_weighting: str | None = None
    sample_weight_alpha: float | None = None
    sample_weight_dv_window_days: int | None = None
    pit_missing_policy: str | None = None
    pit_sample_on_snapshot: bool | None = None
    pit_min_coverage: float | None = None
    symbol_source: str | None = None
    system_theme_key: str | None = None
    pipeline_id: int | None = None


class MLTrainOut(BaseModel):
    id: int
    project_id: int
    pipeline_id: int | None = None
    status: str
    config: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    output_dir: str | None = None
    model_path: str | None = None
    payload_path: str | None = None
    scores_path: str | None = None
    log_path: str | None = None
    message: str | None = None
    is_active: bool = False
    progress: float | None = None
    progress_detail: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None

    class Config:
        from_attributes = True


class MLTrainPageOut(BaseModel):
    items: list[MLTrainOut]
    total: int
    page: int
    page_size: int


class MLPipelineCreate(BaseModel):
    project_id: int
    name: str | None = None
    params: dict[str, Any] | None = None
    notes: str | None = None


class MLPipelineUpdate(BaseModel):
    name: str | None = None
    params: dict[str, Any] | None = None
    notes: str | None = None
    status: str | None = None


class MLPipelineOut(BaseModel):
    id: int
    project_id: int
    name: str | None = None
    status: str
    params: dict[str, Any] | None = None
    notes: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None

    class Config:
        from_attributes = True


class MLPipelineListItem(MLPipelineOut):
    train_job_count: int = 0
    backtest_count: int = 0
    best_train_score: float | None = None
    best_backtest_score: float | None = None
    combined_score: float | None = None
    best_train_job_id: int | None = None
    best_backtest_run_id: int | None = None


class PipelineBacktestOut(BacktestOut):
    score: float | None = None
    score_detail: dict[str, Any] | None = None


class MLPipelineDetailOut(MLPipelineOut):
    train_jobs: list[MLTrainOut] = []
    backtests: list[PipelineBacktestOut] = []
    train_score_summary: dict[str, Any] | None = None
    backtest_score_summary: dict[str, Any] | None = None


class DecisionSnapshotRequest(BaseModel):
    project_id: int
    train_job_id: int | None = None
    pipeline_id: int | None = None
    snapshot_date: str | None = None
    algorithm_parameters: dict[str, Any] | None = None


class DecisionSnapshotItem(BaseModel):
    symbol: str
    snapshot_date: str
    rebalance_date: str
    company_name: str | None = None
    weight: float | None = None
    score: float | None = None
    rank: int | None = None
    theme: str | None = None
    reason: str | None = None
    snapshot_price: float | None = None


class DecisionSnapshotOut(BaseModel):
    id: int
    project_id: int
    pipeline_id: int | None = None
    train_job_id: int | None = None
    status: str
    snapshot_date: str | None = None
    params: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    artifact_dir: str | None = None
    summary_path: str | None = None
    items_path: str | None = None
    filters_path: str | None = None
    message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None

    class Config:
        from_attributes = True


class DecisionSnapshotDetailOut(DecisionSnapshotOut):
    items: list[DecisionSnapshotItem] = []
    filters: list[DecisionSnapshotItem] = []


class DecisionSnapshotPreviewOut(BaseModel):
    id: int | None = None
    project_id: int
    pipeline_id: int | None = None
    train_job_id: int | None = None
    status: str
    snapshot_date: str | None = None
    params: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    artifact_dir: str | None = None
    summary_path: str | None = None
    items_path: str | None = None
    filters_path: str | None = None
    message: str | None = None
    items: list[DecisionSnapshotItem] = []
    filters: list[DecisionSnapshotItem] = []
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


class BacktestTradeOut(BaseModel):
    symbol: str
    time: int
    price: float
    quantity: float
    side: str


class BacktestPositionOut(BaseModel):
    symbol: str
    start_time: int
    end_time: int
    entry_price: float
    exit_price: float
    quantity: float
    profit: bool


class BacktestSymbolOut(BaseModel):
    symbol: str
    trades: int


class BacktestChartOut(BaseModel):
    run_id: int
    symbol: str | None = None
    symbols: list[BacktestSymbolOut]
    trades: list[BacktestTradeOut]
    positions: list[BacktestPositionOut]
    dataset: DatasetOut | None = None


class ReportOut(BaseModel):
    id: int
    run_id: int
    report_type: str
    path: str
    created_at: datetime

    class Config:
        from_attributes = True


class SystemThemeOut(BaseModel):
    id: int
    key: str
    label: str
    source: str
    description: str | None = None
    latest_version_id: int | None = None
    latest_version: str | None = None
    updated_at: datetime | None = None


class SystemThemeVersionOut(BaseModel):
    id: int
    theme_id: int
    version: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class SystemThemePageOut(BaseModel):
    items: list[SystemThemeOut]
    total: int
    page: int
    page_size: int


class SystemThemeVersionPageOut(BaseModel):
    items: list[SystemThemeVersionOut]
    total: int
    page: int
    page_size: int


class SystemThemeImportRequest(BaseModel):
    theme_id: int
    mode: str = "follow_latest"
    version_id: int | None = None
    weight: float | None = None


class SystemThemeImportOut(BaseModel):
    project_id: int
    theme_id: int
    mode: str
    version_id: int | None = None
    project_version_id: int | None = None


class SystemThemeRefreshOut(BaseModel):
    theme_id: int
    updated: bool
    version_id: int | None = None
    version: str | None = None
    affected_projects: int = 0


class ThemeChangeReportOut(BaseModel):
    id: int
    project_id: int
    theme_id: int
    from_version_id: int | None = None
    to_version_id: int
    diff: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ThemeChangeReportPageOut(BaseModel):
    items: list[ThemeChangeReportOut]
    total: int
    page: int
    page_size: int


class UniverseThemeOut(BaseModel):
    key: str
    label: str
    symbols: int
    updated_at: datetime | None = None


class UniverseThemeListOut(BaseModel):
    items: list[UniverseThemeOut]
    updated_at: datetime | None = None


class UniverseThemeSymbolsOut(BaseModel):
    key: str
    label: str | None = None
    symbols: list[str]
    updated_at: datetime | None = None


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


class DatasetCandleOut(BaseModel):
    time: int
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class DatasetLinePointOut(BaseModel):
    time: int
    value: float


class DatasetSeriesOut(BaseModel):
    dataset_id: int
    mode: str
    start: str | None = None
    end: str | None = None
    candles: list[DatasetCandleOut]
    adjusted: list[DatasetLinePointOut]


class DatasetThemeCoverageOut(BaseModel):
    theme_key: str
    theme_label: str | None = None
    total_symbols: int
    covered_symbols: int
    missing_symbols: list[str]
    updated_at: datetime | None = None


class DatasetThemeFetchRequest(BaseModel):
    theme_key: str
    vendor: str | None = "alpha"
    asset_class: str | None = "Equity"
    region: str | None = "US"
    frequency: str | None = "daily"
    auto_sync: bool = True
    only_missing: bool = True


class DatasetThemeFetchOut(BaseModel):
    theme_key: str
    total_symbols: int
    created: int
    reused: int
    queued: int


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
    data_points: int | None = None
    min_interval_days: int | None = None
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
    vendor: str | None = "alpha"
    asset_class: str | None = "Equity"
    region: str | None = "US"
    frequency: str | None = "daily"
    name: str | None = None
    auto_sync: bool = True
    stooq_only: bool = False


class DatasetFetchOut(BaseModel):
    dataset: DatasetOut
    job: DataSyncOut | None = None
    created: bool


class DatasetListingFetchRequest(BaseModel):
    source_path: str | None = None
    status: str | None = "all"
    vendor: str | None = "alpha"
    asset_types: list[str] | None = None
    region: str | None = "US"
    frequency: str | None = "daily"
    only_missing: bool = True
    auto_sync: bool = True
    auto_run: bool = False
    reset_history: bool = False
    limit: int = 500
    offset: int = 0


class DatasetListingFetchOut(BaseModel):
    total_symbols: int
    selected_symbols: int
    created: int
    reused: int
    queued: int
    offset: int
    next_offset: int | None = None


class DataSyncCreate(BaseModel):
    source_path: str | None = None
    date_column: str = "date"
    stooq_only: bool = False
    reset_history: bool = False
    auto_run: bool = True


class DataSyncBatchRequest(BaseModel):
    stooq_only: bool = False
    vendor: str | None = None
    reset_history: bool = False


class DataSyncOut(BaseModel):
    id: int
    dataset_id: int
    dataset_name: str | None = None
    source_path: str
    date_column: str
    reset_history: bool
    retry_count: int | None = None
    next_retry_at: datetime | None = None
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


class DataSyncQueueRunRequest(BaseModel):
    max_jobs: int = 50
    min_delay_seconds: float = 0.9


class DataSyncQueueRunOut(BaseModel):
    started: bool
    running: bool
    pending: int
    max_jobs: int
    min_delay_seconds: float


class DataSyncQueueClearRequest(BaseModel):
    statuses: list[str] | None = None
    only_alpha: bool = False


class DataSyncQueueClearOut(BaseModel):
    deleted: int
    statuses: list[str]
    only_alpha: bool


class AlphaFetchConfigOut(BaseModel):
    alpha_incremental_enabled: bool
    alpha_compact_days: int
    updated_at: str | None = None
    source: str
    path: str


class AlphaFetchConfigUpdate(BaseModel):
    alpha_incremental_enabled: bool | None = None
    alpha_compact_days: int | None = None


class BulkAutoConfigOut(BaseModel):
    status: str
    batch_size: int
    only_missing: bool
    min_delay_seconds: float
    refresh_listing_mode: str
    refresh_listing_ttl_days: int
    project_only: bool
    updated_at: str | None = None
    source: str
    path: str


class BulkAutoConfigUpdate(BaseModel):
    status: str | None = None
    batch_size: int | None = None
    only_missing: bool | None = None
    min_delay_seconds: float | None = None
    refresh_listing_mode: str | None = None
    refresh_listing_ttl_days: int | None = None
    project_only: bool | None = None


class AlphaGapSummaryOut(BaseModel):
    latest_complete: str
    total: int
    with_coverage: int
    missing_coverage: int
    up_to_date: int
    gap_0_30: int
    gap_31_120: int
    gap_120_plus: int
    listing_updated_at: str | None
    listing_age_days: int | None


class DataSyncSpeedOut(BaseModel):
    window_seconds: int
    completed: int
    rate_per_min: float
    running: int
    pending: int
    target_rpm: float | None = None
    effective_min_delay_seconds: float | None = None


class AlphaRateConfigOut(BaseModel):
    max_rpm: float
    rpm_floor: float = 80.0
    rpm_ceil: float
    rpm_step_down: float = 5.0
    rpm_step_up: float = 1.0
    min_delay_seconds: float
    effective_min_delay_seconds: float
    rate_limit_sleep: float
    rate_limit_retries: int
    max_retries: int
    auto_tune: bool = False
    min_delay_floor_seconds: float = 0.1
    min_delay_ceil_seconds: float = 2.0
    tune_step_seconds: float = 0.02
    tune_window_seconds: float = 60.0
    tune_target_ratio_low: float = 0.9
    tune_target_ratio_high: float = 1.05
    tune_cooldown_seconds: float = 10.0
    source: str
    updated_at: str | None
    path: str


class AlphaRateConfigUpdate(BaseModel):
    max_rpm: float | None = None
    rpm_floor: float | None = None
    rpm_ceil: float | None = None
    rpm_step_down: float | None = None
    rpm_step_up: float | None = None
    min_delay_seconds: float | None = None
    rate_limit_sleep: float | None = None
    rate_limit_retries: int | None = None
    max_retries: int | None = None
    auto_tune: bool | None = None
    min_delay_floor_seconds: float | None = None
    min_delay_ceil_seconds: float | None = None
    tune_step_seconds: float | None = None
    tune_window_seconds: float | None = None
    tune_target_ratio_low: float | None = None
    tune_target_ratio_high: float | None = None
    tune_cooldown_seconds: float | None = None


class TradingCalendarConfigOut(BaseModel):
    source: str
    config_source: str | None = None
    exchange: str
    start_date: str
    end_date: str
    refresh_days: int
    override_enabled: bool
    updated_at: str | None
    path: str
    calendar_source: str | None = None
    calendar_exchange: str | None = None
    calendar_start: str | None = None
    calendar_end: str | None = None
    calendar_generated_at: str | None = None
    calendar_sessions: int | None = None
    calendar_path: str | None = None
    overrides_path: str | None = None
    overrides_applied: int | None = None


class TradingCalendarConfigUpdate(BaseModel):
    source: str | None = None
    exchange: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    refresh_days: int | None = None
    override_enabled: bool | None = None


class TradingCalendarRefreshOut(BaseModel):
    status: str
    log_path: str
    return_code: int
    calendar: TradingCalendarConfigOut | None = None


class TradingCalendarPreviewDay(BaseModel):
    date: str
    weekday: int
    is_trading: bool
    in_month: bool | None = None


class TradingCalendarPreviewOut(BaseModel):
    timezone: str
    as_of_date: str | None = None
    month: str | None = None
    latest_trading_day: str | None = None
    next_trading_day: str | None = None
    recent_trading_days: list[str]
    upcoming_trading_days: list[str]
    week_days: list[TradingCalendarPreviewDay]
    month_days: list[TradingCalendarPreviewDay]
    calendar_source: str | None = None
    overrides_applied: int | None = None
    calendar_sessions: int | None = None
    calendar_start: str | None = None
    calendar_end: str | None = None


class AlphaCoverageAuditRequest(BaseModel):
    asset_types: list[str] | None = None
    enqueue_missing: bool = True
    enqueue_missing_adjusted: bool = True
    sample_size: int = 50


class AlphaCoverageAuditOut(BaseModel):
    total_symbols: int
    missing_dataset_count: int
    missing_adjusted_count: int
    enqueued: int
    report_dir: str
    missing_dataset_path: str | None
    missing_adjusted_path: str | None
    sample_missing_dataset: list[str]
    sample_missing_adjusted: list[str]


class TradeCoverageAuditRequest(BaseModel):
    asset_types: list[str] | None = None
    benchmark: str = "SPY"
    vendor_preference: list[str] | None = None
    start: str | None = None
    end: str | None = None
    sample_size: int = 50
    pit_dir: str | None = None
    fundamentals_dir: str | None = None
    pit_fundamentals_dir: str | None = None


class TradeCoverageAuditOut(BaseModel):
    report_dir: str
    price_missing_count: int
    price_missing_path: str | None
    pit_expected_count: int
    pit_existing_count: int
    pit_missing_count: int
    pit_missing_path: str | None
    pit_extra_count: int
    pit_extra_path: str | None
    fundamentals_missing_count: int
    fundamentals_missing_path: str | None
    fundamentals_missing_sample: list[str]
    pit_fundamentals_missing_count: int
    pit_fundamentals_missing_path: str | None
    pit_fundamentals_extra_count: int
    pit_fundamentals_extra_path: str | None


class AlphaNameRepairRequest(BaseModel):
    dry_run: bool = True
    limit: int | None = None
    sample_size: int = 50
    allow_conflicts: bool = False


class AlphaNameRepairItem(BaseModel):
    dataset_id: int
    old_name: str
    new_name: str
    status: str
    moved_paths: list[str] = []
    skipped_paths: list[str] = []
    message: str | None = None


class AlphaNameRepairOut(BaseModel):
    total_candidates: int
    renamed: int
    skipped_same: int
    skipped_conflict: int
    errors: list[str]
    items: list[AlphaNameRepairItem]


class AlphaDuplicateCleanupRequest(BaseModel):
    dry_run: bool = True
    limit: int | None = None
    sample_size: int = 50


class AlphaDuplicateCleanupItem(BaseModel):
    key: str
    keep_id: int
    drop_ids: list[int]
    keep_rows: int
    keep_start: str | None
    keep_end: str | None
    keep_has_adjusted: bool
    message: str | None = None


class AlphaDuplicateCleanupOut(BaseModel):
    total_groups: int
    duplicate_groups: int
    planned_delete: int
    deleted_ids: list[int]
    errors: list[str]
    items: list[AlphaDuplicateCleanupItem]


class BulkSyncCreate(BaseModel):
    status: str = "all"
    batch_size: int = 200
    only_missing: bool = True
    auto_sync: bool = True
    refresh_listing: bool = True
    refresh_listing_mode: str = "stale_only"
    refresh_listing_ttl_days: int = 7
    alpha_incremental_enabled: bool = True
    alpha_compact_days: int = 120
    min_delay_seconds: float = 0.1
    project_only: bool = True


class BulkSyncOut(BaseModel):
    id: int
    status: str
    phase: str
    pause_requested: bool | None = None
    cancel_requested: bool | None = None
    total_symbols: int | None
    processed_symbols: int | None
    created_datasets: int | None
    reused_datasets: int | None
    queued_jobs: int | None
    offset: int
    batch_size: int
    message: str | None
    error: str | None
    enqueued_start_at: datetime | None
    enqueued_end_at: datetime | None
    queue_started_at: datetime | None
    queue_ended_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    updated_at: datetime
    errors: list[dict] | None = None
    pending_sync_jobs: int | None = None
    running_sync_jobs: int | None = None
    completed_sync_jobs: int | None = None

    class Config:
        from_attributes = True


class BulkSyncPageOut(BaseModel):
    items: list[BulkSyncOut]
    total: int
    page: int
    page_size: int


class PitWeeklyJobCreate(BaseModel):
    start: str | None = None
    end: str | None = None
    rebalance_mode: str = "week_open"
    rebalance_day: str = "monday"
    benchmark: str = "SPY"
    market_timezone: str = "America/New_York"
    market_session_open: str = "09:30"
    market_session_close: str = "16:00"
    asset_type: str = "Stock"
    require_data: bool = False
    vendor_preference: str = "Alpha"
    output_dir: str | None = None
    symbol_life: str | None = None
    data_root: str | None = None


class PitWeeklyJobOut(BaseModel):
    id: int
    status: str
    params: dict | None
    output_dir: str | None
    log_path: str | None
    snapshot_count: int | None
    last_snapshot_path: str | None
    message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    class Config:
        from_attributes = True


class PitWeeklyJobPageOut(BaseModel):
    items: list[PitWeeklyJobOut]
    total: int
    page: int
    page_size: int


class PitFundamentalJobCreate(BaseModel):
    start: str | None = None
    end: str | None = None
    report_delay_days: int = 1
    missing_report_delay_days: int = 45
    shares_delay_days: int = 45
    shares_preference: str = "diluted"
    price_source: str = "raw"
    benchmark: str = "SPY"
    vendor_preference: str = "Alpha"
    asset_types: str = "STOCK"
    output_dir: str | None = None
    pit_dir: str | None = None
    fundamentals_dir: str | None = None
    data_root: str | None = None
    refresh_fundamentals: bool = False
    build_pit_fundamentals: bool = True
    resume_fundamentals: bool = False
    resume_from_job_id: int | None = None
    refresh_days: int = 0
    min_delay_seconds: float = 0.45
    max_retries: int = 3
    rate_limit_sleep: float = 10.0
    rate_limit_retries: int = 3
    project_only: bool = True


class PitFundamentalJobOut(BaseModel):
    id: int
    status: str
    params: dict | None
    output_dir: str | None
    log_path: str | None
    snapshot_count: int | None
    last_snapshot_path: str | None
    message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    class Config:
        from_attributes = True


class PitFundamentalJobPageOut(BaseModel):
    items: list[PitFundamentalJobOut]
    total: int
    page: int
    page_size: int


class FactorScoreJobCreate(BaseModel):
    project_id: int
    start: str | None = None
    end: str | None = None
    config_path: str | None = None
    output_path: str | None = None
    cache_dir: str | None = None
    overwrite_cache: bool = False
    data_root: str | None = None
    pit_weekly_dir: str | None = None
    pit_fundamentals_dir: str | None = None
    adjusted_dir: str | None = None
    exclude_symbols: str | None = None


class FactorScoreJobOut(BaseModel):
    id: int
    project_id: int
    status: str
    params: dict | None
    output_dir: str | None
    log_path: str | None
    scores_path: str | None
    message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    class Config:
        from_attributes = True


class AutoWeeklyJobCreate(BaseModel):
    project_id: int
    run_pit_weekly: bool = True
    run_pit_fundamentals: bool = True
    run_backtest: bool = True
    refresh_fundamentals: bool = False
    pit_start: str | None = None
    pit_end: str | None = None
    pit_require_data: bool = False
    pit_vendor_preference: str | None = None
    fundamental_start: str | None = None
    fundamental_end: str | None = None


class AutoWeeklyJobOut(BaseModel):
    id: int
    project_id: int
    status: str
    params: dict | None
    pit_weekly_job_id: int | None
    pit_weekly_log_path: str | None
    pit_fundamental_job_id: int | None
    pit_fundamental_log_path: str | None
    backtest_status: str | None
    backtest_log_path: str | None
    backtest_output_dir: str | None
    backtest_artifact_dir: str | None
    log_path: str | None
    message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    class Config:
        from_attributes = True


class PreTradeTemplateCreate(BaseModel):
    project_id: int | None = None
    name: str
    params: dict | None = None
    is_active: bool = False


class PreTradeTemplateUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None
    is_active: bool | None = None


class PreTradeTemplateOut(BaseModel):
    id: int
    project_id: int | None
    name: str
    params: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PreTradeSettingsUpdate(BaseModel):
    current_template_id: int | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    max_retries: int | None = None
    retry_base_delay_seconds: int | None = None
    retry_max_delay_seconds: int | None = None
    deadline_time: str | None = None
    deadline_timezone: str | None = None
    update_project_only: bool | None = None
    auto_decision_snapshot: bool | None = None


class PreTradeSettingsOut(BaseModel):
    id: int
    current_template_id: int | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    max_retries: int
    retry_base_delay_seconds: int
    retry_max_delay_seconds: int
    deadline_time: str | None
    deadline_timezone: str | None
    update_project_only: bool
    auto_decision_snapshot: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PreTradeRunCreate(BaseModel):
    project_id: int
    template_id: int | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    deadline_at: datetime | None = None
    params: dict | None = None


class PreTradeRunOut(BaseModel):
    id: int
    project_id: int
    template_id: int | None
    status: str
    window_start: datetime | None
    window_end: datetime | None
    deadline_at: datetime | None
    params: dict | None
    message: str | None
    fallback_used: bool
    fallback_run_id: int | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class PreTradeRunPageOut(BaseModel):
    items: list[PreTradeRunOut]
    total: int
    page: int
    page_size: int


class PreTradeStepOut(BaseModel):
    id: int
    run_id: int
    step_key: str
    step_order: int
    status: str
    progress: float | None
    retry_count: int
    next_retry_at: datetime | None
    message: str | None
    log_path: str | None
    params: dict | None
    artifacts: dict | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class PreTradeRunDetail(BaseModel):
    run: PreTradeRunOut
    steps: list[PreTradeStepOut]


class PreTradeSummaryOut(BaseModel):
    run: PreTradeRunOut | None
    steps_total: int
    steps_success: int
    steps_failed: int
    steps_running: int
    steps_queued: int
    steps_skipped: int
    progress: float


class PreTradeTelegramTest(BaseModel):
    message: str | None = None


class PreTradeTelegramTestOut(BaseModel):
    ok: bool

class IBSettingsUpdate(BaseModel):
    host: str | None = None
    port: int | None = None
    client_id: int | None = None
    account_id: str | None = None
    mode: str | None = None
    market_data_type: str | None = None
    api_mode: str | None = None
    use_regulatory_snapshot: bool | None = None


class IBSettingsOut(BaseModel):
    id: int
    host: str
    port: int
    client_id: int
    account_id: str | None
    mode: str
    market_data_type: str
    api_mode: str
    use_regulatory_snapshot: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IBStreamStartRequest(BaseModel):
    project_id: int
    decision_snapshot_id: int | None = None
    symbols: list[str] | None = None
    max_symbols: int | None = None
    market_data_type: str | None = None


class IBStreamStatusOut(BaseModel):
    status: str
    last_heartbeat: str | None
    subscribed_symbols: list[str]
    ib_error_count: int
    last_error: str | None
    market_data_type: str | None


class IBStreamSnapshotOut(BaseModel):
    symbol: str
    data: dict | None
    error: str | None = None


class IBAccountSummaryOut(BaseModel):
    items: dict[str, float | str | None] = Field(default_factory=dict)
    refreshed_at: datetime | None = None
    source: str | None = None
    stale: bool = False
    full: bool = False


class IBAccountPositionOut(BaseModel):
    symbol: str
    position: float
    avg_cost: float | None = None
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    account: str | None = None
    currency: str | None = None


class IBAccountPositionsOut(BaseModel):
    items: list[IBAccountPositionOut] = Field(default_factory=list)
    refreshed_at: datetime | None = None
    stale: bool = False


class TradeSettingsOut(BaseModel):
    id: int
    risk_defaults: dict | None = None
    execution_data_source: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeSettingsUpdate(BaseModel):
    risk_defaults: dict | None = None
    execution_data_source: str | None = None


class TradeGuardStateOut(BaseModel):
    id: int
    project_id: int
    trade_date: date
    mode: str
    status: str
    halt_reason: dict | None
    risk_triggers: int
    order_failures: int
    market_data_errors: int
    day_start_equity: float | None
    equity_peak: float | None
    last_equity: float | None
    last_valuation_ts: datetime | None
    valuation_source: str | None
    cooldown_until: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeGuardEvaluateRequest(BaseModel):
    project_id: int
    mode: str = "paper"
    risk_params: dict | None = None


class TradeGuardEvaluateOut(BaseModel):
    state: TradeGuardStateOut
    result: dict


class IBContractRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    sec_type: str | None = None
    exchange: str | None = None
    currency: str | None = None
    use_project_symbols: bool = True


class IBContractCacheOut(BaseModel):
    id: int
    symbol: str
    sec_type: str
    exchange: str
    primary_exchange: str | None
    currency: str
    con_id: int
    local_symbol: str | None
    multiplier: str | None
    detail: dict | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IBContractRefreshOut(BaseModel):
    total: int
    updated: int
    skipped: int
    errors: list[str]
    duration_sec: float


class IBMarketSnapshotRequest(BaseModel):
    symbols: list[str]
    store: bool = True
    fallback_history: bool = False
    history_duration: str = "5 D"
    history_bar_size: str = "1 day"
    history_use_rth: bool = True


class IBMarketSnapshotItem(BaseModel):
    symbol: str
    data: dict | None
    error: str | None = None


class IBMarketSnapshotOut(BaseModel):
    total: int
    success: int
    items: list[IBMarketSnapshotItem]


class IBMarketHealthRequest(BaseModel):
    symbols: list[str] | None = None
    use_project_symbols: bool = False
    min_success_ratio: float = 1.0
    fallback_history: bool = True
    history_duration: str = "5 D"
    history_bar_size: str = "1 day"
    history_use_rth: bool = True


class IBMarketHealthOut(BaseModel):
    status: str
    total: int
    success: int
    missing_symbols: list[str]
    errors: list[str]


class IBHistoryJobCreate(BaseModel):
    symbols: list[str] | None = None
    use_project_symbols: bool = False
    duration: str = "30 D"
    bar_size: str = "1 day"
    use_rth: bool = True
    store: bool = True
    min_delay_seconds: float = 0.2
    resume: bool = True


class IBHistoryJobOut(BaseModel):
    id: int
    status: str
    params: dict | None
    total_symbols: int | None
    processed_symbols: int | None
    success_symbols: int | None
    failed_symbols: int | None
    log_path: str | None
    message: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class IBHistoricalRequest(BaseModel):
    symbol: str
    duration: str = "30 D"
    bar_size: str = "1 day"
    end_datetime: str | None = None
    use_rth: bool = True
    store: bool = True


class IBHistoricalOut(BaseModel):
    symbol: str
    bars: int
    path: str | None = None
    error: str | None = None


class IBConnectionHeartbeat(BaseModel):
    status: str | None = None
    message: str | None = None


class IBConnectionStateOut(BaseModel):
    id: int
    status: str
    message: str | None
    last_heartbeat: datetime | None
    degraded_since: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class IBHealthOut(BaseModel):
    connection_status: str
    stream_status: str
    stream_last_heartbeat: str | None = None


class IBStatusOverviewOut(BaseModel):
    connection: dict
    config: dict
    stream: dict
    snapshot_cache: dict
    orders: dict
    alerts: dict
    partial: bool = False
    errors: list[str] = []
    refreshed_at: datetime


class TradeOrderCreate(BaseModel):
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "MKT"
    limit_price: float | None = None
    params: dict | None = None


class TradeOrderStatusUpdate(BaseModel):
    status: str
    filled_quantity: float | None = None
    avg_fill_price: float | None = None
    params: dict | None = None


class TradeRunCreate(BaseModel):
    project_id: int
    decision_snapshot_id: int | None = None
    mode: str = "paper"
    orders: list[TradeOrderCreate] = []
    live_confirm_token: str | None = None
    require_market_health: bool = True
    health_min_success_ratio: float = 1.0
    health_fallback_history: bool = True
    health_history_duration: str = "5 D"
    health_history_bar_size: str = "1 day"
    health_history_use_rth: bool = True


class TradeRunOut(BaseModel):
    id: int
    project_id: int
    decision_snapshot_id: int | None
    mode: str
    status: str
    params: dict | None
    message: str | None
    orders_created: int | None = None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeRunExecuteRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    live_confirm_token: str | None = None


class TradeRunExecuteOut(BaseModel):
    run_id: int
    status: str
    filled: int
    cancelled: int
    rejected: int
    skipped: int
    message: str | None
    dry_run: bool


class TradeFillOut(BaseModel):
    id: int
    exec_id: str | None = None
    fill_quantity: float
    fill_price: float
    currency: str | None = None
    exchange: str | None = None

    class Config:
        from_attributes = True


class TradeOrderOut(BaseModel):
    id: int
    run_id: int | None
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None
    status: str
    filled_quantity: float
    avg_fill_price: float | None
    ib_order_id: int | None = None
    ib_perm_id: int | None = None
    rejected_reason: str | None = None
    params: dict | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeFillDetailOut(BaseModel):
    id: int
    order_id: int
    exec_id: str | None = None
    fill_quantity: float
    fill_price: float
    commission: float | None = None
    fill_time: datetime | None = None
    currency: str | None = None
    exchange: str | None = None

    class Config:
        from_attributes = True


class TradeRunDetailOut(BaseModel):
    run: TradeRunOut
    orders: list[TradeOrderOut]
    fills: list[TradeFillDetailOut]
    last_update_at: datetime | None


class TradeSymbolSummaryOut(BaseModel):
    symbol: str
    target_weight: float | None = None
    target_value: float | None = None
    filled_qty: float
    avg_fill_price: float | None = None
    filled_value: float
    pending_qty: float
    last_status: str | None = None
    delta_value: float | None = None
    delta_weight: float | None = None
    fill_ratio: float | None = None


class TradeSymbolSummaryPageOut(BaseModel):
    items: list[TradeSymbolSummaryOut]
    last_update_at: datetime | None


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


class AlgorithmUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    language: str | None = None
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
    params: dict | None = None


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


class AlgorithmVersionDetailOut(BaseModel):
    id: int
    algorithm_id: int
    version: str | None
    description: str | None
    language: str
    file_path: str | None
    type_name: str | None
    content_hash: str | None
    content: str | None
    params: dict | None
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


class AlgorithmSelfTestCreate(BaseModel):
    version_id: int | None = None
    benchmark: str | None = "SPY"
    parameters: dict[str, Any] | None = None
