from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.covered_call_review import build_covered_call_review
from app.services.trade_option_models import CoveredCallReviewRequest


def test_build_covered_call_review_blocks_without_token(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_review.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(
        'app.services.covered_call_review.prepare_covered_call_execution',
        lambda *_a, **_k: {
            'mode': 'paper',
            'status': 'blocked',
            'gate_reason': 'shares_below_100',
            'eligible': None,
            'order_plan': None,
            'artifacts': {'summary': '/tmp/prepare-summary.json'},
        },
    )
    monkeypatch.setattr('app.services.covered_call_review.resolve_bridge_root', lambda: tmp_path / 'bridge')
    monkeypatch.setattr('app.services.covered_call_review.load_gateway_runtime_health', lambda *_a, **_k: {'state': 'healthy', 'last_probe_result': 'success'})
    monkeypatch.setattr('app.services.covered_call_review.read_open_orders', lambda *_a, **_k: {'items': [], 'stale': False})
    monkeypatch.setattr('app.services.covered_call_review.get_account_positions_cached', lambda *_a, **_k: {'items': [], 'stale': False})
    audits = []
    monkeypatch.setattr('app.services.covered_call_review.record_audit', lambda *args, **kwargs: audits.append(kwargs))

    result = build_covered_call_review(object(), CoveredCallReviewRequest(mode='paper', symbol='AAPL', dry_run=True))

    assert result['status'] == 'blocked'
    assert result['approval_token'] is None
    assert result['review_id'] is None
    assert result['gate_reason'] == 'shares_below_100'
    assert result['artifacts']['summary']
    assert not audits



def test_build_covered_call_review_generates_ready_token_and_audit(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_review.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(
        'app.services.covered_call_review.prepare_covered_call_execution',
        lambda *_a, **_k: {
            'mode': 'paper',
            'status': 'ready',
            'gate_reason': None,
            'eligible': {'symbol': 'AAPL', 'shares': 200, 'coverable_contracts': 2},
            'order_plan': {
                'underlying_symbol': 'AAPL',
                'sec_type': 'OPT',
                'side': 'SELL',
                'expiry': '2026-05-15',
                'strike': 230.0,
                'right': 'C',
                'contracts': 2,
                'quantity': 2,
                'multiplier': 100,
                'order_type': 'LMT',
                'limit_price': 1.25,
                'dry_run': True,
                'risk_tags': [],
            },
            'artifacts': {'summary': '/tmp/prepare-summary.json'},
        },
    )
    monkeypatch.setattr('app.services.covered_call_review.resolve_bridge_root', lambda: tmp_path / 'bridge')
    monkeypatch.setattr('app.services.covered_call_review.load_gateway_runtime_health', lambda *_a, **_k: {'state': 'healthy', 'last_probe_result': 'success', 'failure_count': 0})
    monkeypatch.setattr('app.services.covered_call_review.read_open_orders', lambda *_a, **_k: {'items': [], 'stale': False})
    monkeypatch.setattr(
        'app.services.covered_call_review.get_account_positions_cached',
        lambda *_a, **_k: {'items': [{'symbol': 'AAPL', 'quantity': 200, 'market_price': 225.0}], 'stale': False},
    )
    audits = []
    monkeypatch.setattr('app.services.covered_call_review.record_audit', lambda *args, **kwargs: audits.append(kwargs))

    result = build_covered_call_review(object(), CoveredCallReviewRequest(mode='paper', symbol='AAPL', dry_run=True))

    assert result['status'] == 'ready'
    assert result['approval_token']
    assert result['review_id']
    assert result['approval_expires_at']
    assert result['runtime_summary']['state'] == 'healthy'
    assert result['position_summary']['shares'] == 200
    assert result['open_orders_summary']['symbol_conflict'] is False
    assert Path(result['artifacts']['summary']).exists()
    assert Path(result['artifacts']['bundle']).exists()
    assert len(audits) == 1
    assert audits[0]['action'] == 'covered_call_review_prepared'



def test_build_covered_call_review_preserves_review_required_and_risk_tags(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_review.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr(
        'app.services.covered_call_review.prepare_covered_call_execution',
        lambda *_a, **_k: {
            'mode': 'paper',
            'status': 'review_required',
            'gate_reason': 'risk_tags_present',
            'eligible': {'symbol': 'AAPL', 'shares': 200, 'coverable_contracts': 2},
            'order_plan': {
                'underlying_symbol': 'AAPL',
                'sec_type': 'OPT',
                'side': 'SELL',
                'expiry': '2026-05-15',
                'strike': 230.0,
                'right': 'C',
                'contracts': 2,
                'quantity': 2,
                'multiplier': 100,
                'order_type': 'LMT',
                'limit_price': 1.25,
                'dry_run': True,
                'risk_tags': ['tight_otm_buffer'],
            },
            'artifacts': {'summary': '/tmp/prepare-summary.json'},
        },
    )
    monkeypatch.setattr('app.services.covered_call_review.resolve_bridge_root', lambda: tmp_path / 'bridge')
    monkeypatch.setattr('app.services.covered_call_review.load_gateway_runtime_health', lambda *_a, **_k: {'state': 'healthy', 'last_probe_result': 'success', 'failure_count': 0})
    monkeypatch.setattr('app.services.covered_call_review.read_open_orders', lambda *_a, **_k: {'items': [], 'stale': False})
    monkeypatch.setattr(
        'app.services.covered_call_review.get_account_positions_cached',
        lambda *_a, **_k: {'items': [{'symbol': 'AAPL', 'quantity': 200, 'market_price': 225.0}], 'stale': False},
    )
    monkeypatch.setattr('app.services.covered_call_review.record_audit', lambda *args, **kwargs: None)

    result = build_covered_call_review(object(), CoveredCallReviewRequest(mode='paper', symbol='AAPL', dry_run=True))

    assert result['status'] == 'review_required'
    assert result['approval_token']
    assert result['gate_reason'] == 'risk_tags_present'
    assert result['order_plan']['risk_tags'] == ['tight_otm_buffer']
