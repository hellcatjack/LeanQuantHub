from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.covered_call_execution import prepare_covered_call_execution
from app.services.trade_option_models import CoveredCallExecutionPrepareRequest


def test_prepare_covered_call_execution_blocks_when_no_eligible(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_execution.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(
        'app.services.covered_call_execution.run_covered_call_pilot',
        lambda *_a, **_k: {
            'mode': 'paper',
            'status': 'ok',
            'eligible': [],
            'rejected': [{'symbol': 'AAPL', 'reason': 'shares_below_100'}],
            'artifacts': {'summary': '/tmp/pilot-summary.json'},
        },
    )

    result = prepare_covered_call_execution(
        object(),
        CoveredCallExecutionPrepareRequest(mode='paper', symbol='AAPL', dry_run=True),
    )

    assert result['status'] == 'blocked'
    assert result['gate_reason'] == 'shares_below_100'
    assert result['order_plan'] is None
    assert result['artifacts']['summary']



def test_prepare_covered_call_execution_marks_review_required_for_risk_tags(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_execution.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(
        'app.services.covered_call_execution.run_covered_call_pilot',
        lambda *_a, **_k: {
            'mode': 'paper',
            'status': 'ok',
            'eligible': [
                {
                    'symbol': 'AAPL',
                    'shares': 200,
                    'coverable_contracts': 2,
                    'candidate_count': 1,
                    'recommended': {
                        'symbol': 'AAPL',
                        'shares': 200,
                        'coverable_contracts': 2,
                        'expiry': '2026-05-15',
                        'strike': 230.0,
                        'right': 'C',
                        'contracts': 2,
                        'bid': 1.2,
                        'ask': 1.3,
                        'mid': 1.25,
                        'underlying_price': 225.0,
                        'dte': 30,
                        'spread_ratio': 0.08,
                        'moneyness_pct': 0.022,
                        'risk_tags': ['tight_otm_buffer'],
                    },
                }
            ],
            'rejected': [],
            'artifacts': {'summary': '/tmp/pilot-summary.json'},
        },
    )

    result = prepare_covered_call_execution(
        object(),
        CoveredCallExecutionPrepareRequest(mode='paper', symbol='AAPL', dry_run=True),
    )

    assert result['status'] == 'review_required'
    assert result['gate_reason'] == 'risk_tags_present'
    assert result['order_plan']['limit_price'] == 1.25
    assert result['order_plan']['risk_tags'] == ['tight_otm_buffer']



def test_prepare_covered_call_execution_builds_ready_option_order_plan(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_execution.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(
        'app.services.covered_call_execution.run_covered_call_pilot',
        lambda *_a, **_k: {
            'mode': 'paper',
            'status': 'ok',
            'eligible': [
                {
                    'symbol': 'AAPL',
                    'shares': 200,
                    'coverable_contracts': 2,
                    'candidate_count': 1,
                    'recommended': {
                        'symbol': 'AAPL',
                        'shares': 200,
                        'coverable_contracts': 2,
                        'expiry': '2026-05-15',
                        'strike': 230.0,
                        'right': 'C',
                        'contracts': 2,
                        'bid': 1.2,
                        'ask': 1.3,
                        'mid': 1.25,
                        'underlying_price': 225.0,
                        'dte': 30,
                        'spread_ratio': 0.08,
                        'moneyness_pct': 0.022,
                        'risk_tags': [],
                    },
                }
            ],
            'rejected': [],
            'artifacts': {'summary': '/tmp/pilot-summary.json'},
        },
    )

    result = prepare_covered_call_execution(
        object(),
        CoveredCallExecutionPrepareRequest(mode='paper', symbol='AAPL', dry_run=True),
    )

    assert result['status'] == 'ready'
    assert result['gate_reason'] is None
    plan = result['order_plan']
    assert plan['underlying_symbol'] == 'AAPL'
    assert plan['sec_type'] == 'OPT'
    assert plan['side'] == 'SELL'
    assert plan['expiry'] == '2026-05-15'
    assert plan['strike'] == 230.0
    assert plan['right'] == 'C'
    assert plan['multiplier'] == 100
    assert plan['contracts'] == 2
    assert plan['quantity'] == 2
    assert plan['order_type'] == 'LMT'
    assert plan['limit_price'] == 1.25
    assert Path(result['artifacts']['summary']).exists()
    assert Path(result['artifacts']['plan']).exists()
