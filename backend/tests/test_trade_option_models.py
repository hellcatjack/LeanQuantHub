from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.trade_option_models import (
    CoveredCallExecutionPrepareRequest,
    CoveredCallPilotRequest,
    CoveredCallRecommendation,
    CoveredCallReviewRequest,
    CoveredCallReviewResult,
    CoveredCallSubmitRequest,
    CoveredCallSubmitResult,
    OptionOrderPlan,
)


def test_covered_call_models_default_to_paper_dry_run() -> None:
    payload = CoveredCallPilotRequest()

    assert payload.mode == "paper"
    assert payload.dry_run is True
    assert payload.dte_min == 21
    assert payload.dte_max == 45
    assert payload.max_spread_ratio == 0.15


def test_covered_call_recommendation_serializes_contract_shape() -> None:
    rec = CoveredCallRecommendation(
        symbol="AAPL",
        shares=200,
        coverable_contracts=2,
        expiry="2026-05-15",
        strike=230.0,
        right="C",
        contracts=2,
        bid=1.2,
        ask=1.3,
        mid=1.25,
    )

    assert rec.right == "C"
    assert rec.contracts == 2
    assert rec.mid == 1.25



def test_covered_call_recommendation_includes_risk_metrics():
    rec = CoveredCallRecommendation(
        symbol="AAPL",
        shares=200,
        coverable_contracts=2,
        expiry="2026-05-15",
        strike=230.0,
        right="C",
        contracts=2,
        bid=1.2,
        ask=1.3,
        mid=1.25,
        underlying_price=225.0,
        dte=30,
        spread_ratio=0.08,
        moneyness_pct=0.0222,
        risk_tags=["tight_otm_buffer"],
    )
    assert rec.underlying_price == 225.0
    assert rec.dte == 30
    assert rec.spread_ratio == 0.08
    assert rec.risk_tags == ["tight_otm_buffer"]



def test_covered_call_execution_prepare_request_defaults_to_paper_dry_run() -> None:
    payload = CoveredCallExecutionPrepareRequest(symbol="AAPL")

    assert payload.mode == "paper"
    assert payload.dry_run is True
    assert payload.symbol == "AAPL"


def test_option_order_plan_defaults_multiplier_and_limit_order() -> None:
    plan = OptionOrderPlan(
        underlying_symbol="AAPL",
        sec_type="OPT",
        side="SELL",
        expiry="2026-05-15",
        strike=230.0,
        right="C",
        contracts=2,
        quantity=2,
        limit_price=1.25,
    )

    assert plan.multiplier == 100
    assert plan.order_type == "LMT"
    assert plan.limit_price == 1.25



def test_covered_call_review_request_defaults_to_paper_dry_run() -> None:
    payload = CoveredCallReviewRequest(symbol="AAPL")

    assert payload.mode == "paper"
    assert payload.dry_run is True
    assert payload.symbol == "AAPL"


def test_covered_call_review_result_allows_token_and_review_id() -> None:
    result = CoveredCallReviewResult(
        mode="paper",
        status="ready",
        review_id="review-1",
        approval_token="token-1",
        approval_expires_at="2026-04-07T21:30:00Z",
        runtime_summary={"state": "healthy"},
        position_summary={"shares": 200},
        open_orders_summary={"symbol_conflict": False},
    )

    assert result.review_id == "review-1"
    assert result.approval_token == "token-1"
    assert result.runtime_summary["state"] == "healthy"


def test_covered_call_submit_request_defaults_to_paper_real_submit() -> None:
    payload = CoveredCallSubmitRequest(
        symbol="AAPL",
        review_id="options_review_1",
        approval_token="token-1",
    )

    assert payload.mode == "paper"
    assert payload.dry_run is False
    assert payload.symbol == "AAPL"
    assert payload.review_id == "options_review_1"


def test_covered_call_submit_result_captures_command_outcome() -> None:
    result = CoveredCallSubmitResult(
        mode="paper",
        status="submitted",
        review_id="options_review_1",
        command_id="submit_order_cc_1",
        command_result_status="submitted",
        runtime_summary={"state": "healthy"},
        position_summary={"shares": 200},
        open_orders_summary={"symbol_conflict": False},
    )

    assert result.command_id == "submit_order_cc_1"
    assert result.command_result_status == "submitted"
