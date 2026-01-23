from app.routes import trade


def test_trade_run_orders_endpoint_registered():
    paths = {route.path for route in trade.router.routes}
    assert "/api/trade/runs/{run_id}/orders" in paths
