from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.covered_call_pilot import run_covered_call_pilot
from app.services.trade_option_models import CoveredCallPilotRequest


def _expiry(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def test_run_covered_call_pilot_returns_enriched_recommendation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr('app.services.covered_call_pilot.ARTIFACT_ROOT', tmp_path)
    monkeypatch.setattr('app.services.covered_call_pilot.resolve_bridge_root', lambda: tmp_path / 'bridge')
    monkeypatch.setattr('app.services.covered_call_pilot.load_gateway_runtime_health', lambda *_a, **_k: {'state': 'healthy'})
    monkeypatch.setattr('app.services.covered_call_pilot.get_gateway_trade_block_state', lambda *_a, **_k: None)
    monkeypatch.setattr('app.services.covered_call_pilot.read_open_orders', lambda *_a, **_k: {'items': [], 'stale': False})
    monkeypatch.setattr(
        'app.services.covered_call_pilot.get_account_positions_cached',
        lambda *_a, **_k: {
            'items': [{'symbol': 'AAPL', 'quantity': 200, 'market_value': 45000.0}],
            'stale': False,
        },
    )
    monkeypatch.setattr(
        'app.services.covered_call_pilot.fetch_option_candidates',
        lambda *_a, **_k: [
            {
                'symbol': 'AAPL',
                'expiry': _expiry(24),
                'strike': 226.0,
                'underlying_price': 225.0,
                'right': 'C',
                'bid': 1.0,
                'ask': 1.14,
            }
        ],
    )

    result = run_covered_call_pilot(object(), CoveredCallPilotRequest(mode='paper', dry_run=True, symbols=['AAPL']))

    assert result['status'] == 'ok'
    assert len(result['eligible']) == 1
    eligible = result['eligible'][0]
    assert eligible['candidate_count'] == 1
    rec = eligible['recommended']
    assert rec['underlying_price'] == 225.0
    assert rec['dte'] > 0
    assert rec['spread_ratio'] > 0
    assert 'tight_otm_buffer' in rec['risk_tags']
    assert Path(result['artifacts']['summary']).exists()
    assert Path(result['artifacts']['orders']).exists()
