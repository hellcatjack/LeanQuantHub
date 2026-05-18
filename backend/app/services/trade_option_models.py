from __future__ import annotations

from pydantic import BaseModel, Field


class CoveredCallPilotRequest(BaseModel):
    mode: str = "paper"
    symbols: list[str] = Field(default_factory=list)
    max_candidates_per_symbol: int = 5
    dte_min: int = 21
    dte_max: int = 45
    max_spread_ratio: float = 0.15
    dry_run: bool = True


class CoveredCallRecommendation(BaseModel):
    symbol: str
    shares: int
    coverable_contracts: int
    expiry: str
    strike: float
    right: str
    contracts: int
    bid: float
    ask: float
    mid: float
    underlying_price: float = 0.0
    dte: int = 0
    spread_ratio: float = 0.0
    moneyness_pct: float = 0.0
    risk_tags: list[str] = Field(default_factory=list)


class CoveredCallExecutionPrepareRequest(BaseModel):
    mode: str = "paper"
    symbol: str
    max_candidates_per_symbol: int = 5
    dte_min: int = 21
    dte_max: int = 45
    max_spread_ratio: float = 0.15
    dry_run: bool = True


class OptionOrderPlan(BaseModel):
    underlying_symbol: str
    sec_type: str = "OPT"
    side: str
    expiry: str
    strike: float
    right: str
    contracts: int
    quantity: int
    multiplier: int = 100
    order_type: str = "LMT"
    limit_price: float
    dry_run: bool = True
    risk_tags: list[str] = Field(default_factory=list)


class CoveredCallReviewRequest(BaseModel):
    mode: str = "paper"
    symbol: str
    max_candidates_per_symbol: int = 5
    dte_min: int = 21
    dte_max: int = 45
    max_spread_ratio: float = 0.15
    dry_run: bool = True


class CoveredCallReviewArtifacts(BaseModel):
    summary: str | None = None
    bundle: str | None = None
    prepare_summary: str | None = None


class CoveredCallReviewResult(BaseModel):
    mode: str
    status: str
    gate_reason: str | None = None
    review_id: str | None = None
    approval_token: str | None = None
    approval_expires_at: str | None = None
    eligible: dict | None = None
    order_plan: dict | None = None
    runtime_summary: dict = Field(default_factory=dict)
    position_summary: dict = Field(default_factory=dict)
    open_orders_summary: dict = Field(default_factory=dict)
    artifacts: CoveredCallReviewArtifacts | None = None


class CoveredCallSubmitRequest(BaseModel):
    mode: str = "paper"
    symbol: str
    review_id: str
    approval_token: str
    dry_run: bool = False


class CoveredCallSubmitArtifacts(BaseModel):
    summary: str | None = None
    submit_request: str | None = None
    command_result: str | None = None
    review_bundle: str | None = None


class CoveredCallSubmitResult(BaseModel):
    mode: str
    status: str
    gate_reason: str | None = None
    review_id: str
    command_id: str | None = None
    command_result_status: str | None = None
    order_plan: dict | None = None
    runtime_summary: dict = Field(default_factory=dict)
    position_summary: dict = Field(default_factory=dict)
    open_orders_summary: dict = Field(default_factory=dict)
    artifacts: CoveredCallSubmitArtifacts | None = None


class CoveredCallReceiptRequest(BaseModel):
    mode: str = "paper"
    review_id: str
    command_id: str


class CoveredCallReceiptArtifacts(BaseModel):
    summary: str | None = None
    command_result: str | None = None
    review_bundle: str | None = None


class CoveredCallReceiptResult(BaseModel):
    mode: str
    status: str
    receipt_state: str
    gate_reason: str | None = None
    review_id: str
    command_id: str
    command_result_status: str | None = None
    runtime_summary: dict = Field(default_factory=dict)
    open_orders_summary: dict = Field(default_factory=dict)
    artifacts: CoveredCallReceiptArtifacts | None = None


class CoveredCallTimelineRequest(BaseModel):
    mode: str = "paper"
    review_id: str


class CoveredCallTimelineArtifacts(BaseModel):
    summary: str | None = None
    review_bundle: str | None = None
    latest_submit_summary: str | None = None
    latest_receipt_summary: str | None = None


class CoveredCallTimelineResult(BaseModel):
    mode: str
    status: str
    timeline_state: str
    review_id: str
    latest_submit: dict | None = None
    latest_receipt: dict | None = None
    stages: list[dict] = Field(default_factory=list)
    artifacts: CoveredCallTimelineArtifacts | None = None


class CoveredCallAuditRequest(BaseModel):
    mode: str = "paper"
    review_id: str


class CoveredCallAuditArtifacts(BaseModel):
    summary: str | None = None
    review_bundle: str | None = None
    timeline_summary: str | None = None
    latest_submit_summary: str | None = None
    latest_receipt_summary: str | None = None


class CoveredCallAuditResult(BaseModel):
    mode: str
    status: str
    timeline_state: str
    review_id: str
    review: dict | None = None
    submit: dict | None = None
    receipt: dict | None = None
    timeline: dict | None = None
    artifacts: CoveredCallAuditArtifacts | None = None


class CoveredCallAuditRecentRequest(BaseModel):
    mode: str = "paper"
    limit: int = 10
    offset: int = 0
    query: str = ""


class CoveredCallAuditRecentResult(BaseModel):
    mode: str
    total: int = 0
    has_more: bool = False
    items: list[dict] = Field(default_factory=list)
