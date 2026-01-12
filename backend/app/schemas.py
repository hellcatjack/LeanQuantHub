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
    resume_fundamentals: bool = False
    resume_from_job_id: int | None = None
    refresh_days: int = 0
    min_delay_seconds: float = 0.45
    max_retries: int = 3
    rate_limit_sleep: float = 10.0
    rate_limit_retries: int = 3


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
