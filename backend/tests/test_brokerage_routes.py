from app.routes import brokerage as brokerage_routes


def test_brokerage_settings_route_registered():
    paths = {route.path for route in brokerage_routes.router.routes}
    assert "/api/brokerage/settings" in paths
