from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.routes import brokerage as brokerage_routes


def test_brokerage_settings_route_registered():
    paths = {route.path for route in brokerage_routes.router.routes}
    assert "/api/brokerage/settings" in paths
