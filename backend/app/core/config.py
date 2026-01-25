from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_user: str = ""
    db_password: str = ""
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "stocklean"
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
    market_timezone: str = "America/New_York"
    market_session_open: str = "09:30"
    market_session_close: str = "16:00"

    class Config:
        env_file = ".env"
        env_prefix = ""
        case_sensitive = False


settings = Settings()
