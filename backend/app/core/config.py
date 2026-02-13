from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_user: str = ""
    db_password: str = ""
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "stocklean"
    db_pool_size: int = 20
    db_pool_max_overflow: int = 40
    db_pool_timeout_seconds: int = 15
    db_pool_recycle_seconds: int = 1800
    artifact_root: str = str(Path("/app/stocklean/artifacts"))
    lean_launcher_path: str = ""
    lean_launcher_dll: str = ""
    lean_config_template: str = ""
    lean_algorithm_path: str = ""
    lean_data_folder: str = ""
    data_root: str = ""
    lean_python_venv: str = ""
    python_dll: str = ""
    dotnet_path: str = "dotnet"
    dotnet_root: str = ""
    alpha_vantage_api_key: str = ""
    alpha_vantage_entitlement: str = "delayed"
    alpha_max_rpm: int = 154
    alpha_min_delay_seconds: float = 0.12
    alpha_rate_limit_sleep: float = 10.0
    alpha_rate_limit_retries: int = 3
    alpha_max_retries: int = 3
    ml_python_path: str = ""
    ib_client_id_base: int = 1000
    ib_client_id_live_offset: int = 5000
    ib_client_id_pool_base: int = 2000
    ib_client_id_pool_size: int = 32
    ib_client_id_lease_ttl_seconds: int = 300
    # Lean bridge leader IB client id override.
    # - Set to -1 to use the IB settings row (legacy fallback).
    # - Set to 0 to use the IB "master" API client id so leader can observe/cancel cross-client orders.
    lean_bridge_leader_client_id: int = 0
    # IB brokerage response wait (seconds). Reducing this prevents the bridge from hanging for minutes
    # on cancel/update requests when TWS doesn't respond (or responds with "not found").
    lean_ib_response_timeout_seconds: int = 20
    lean_bridge_heartbeat_timeout_seconds: int = 60
    lean_bridge_leader_check_seconds: int = 2
    lean_bridge_watchdog_heavy_task_interval_seconds: int = 15
    lean_bridge_watchlist_refresh_seconds: int = 5
    lean_bridge_snapshot_seconds: int = 2
    lean_bridge_open_orders_seconds: int = 2
    lean_bridge_executions_seconds: int = 2
    lean_bridge_commands_seconds: int = 1
    lean_pool_size: int = 10
    lean_pool_max_active_connections: int = 10
    lean_pool_heartbeat_ttl_seconds: int = 20
    lean_pool_leader_restart_limit: int = 3
    market_timezone: str = "America/New_York"
    market_session_open: str = "09:30"
    market_session_close: str = "16:00"

    class Config:
        env_file = ".env"
        env_prefix = ""
        case_sensitive = False


settings = Settings()
