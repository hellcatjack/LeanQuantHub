import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core import config


def test_lean_pool_settings_present():
    assert hasattr(config.settings, "lean_pool_size")
    assert hasattr(config.settings, "lean_pool_max_active_connections")
    assert hasattr(config.settings, "lean_pool_heartbeat_ttl_seconds")
    assert hasattr(config.settings, "lean_pool_leader_restart_limit")
