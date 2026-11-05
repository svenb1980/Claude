"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    refresh_hour: int
    timezone: str
    market_provider: str
    scheduler_enabled: bool
    screener_batch: int
    ask_backend: str = "claude-code"
    ask_cli_path: str = ""
    ask_cli_model: str = ""
    ask_model: str = "claude-opus-5-5"
    ask_daily_limit: int = 50

    @property
    def db_path(self) -> Path:
        return self.data_dir / "stock-analyzer.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def secret_key(self) -> str:
        """Session-signing key, created once and kept in the data volume."""
        path = self.data_dir / "secret.key"
        if not path.exists():
            path.write_text(secrets.token_hex(32), encoding="ascii")
        return path.read_text(encoding="ascii").strip()


def load_config() -> Config:
    cfg = Config(
        data_dir=Path(os.environ.get("DATA_DIR", "./data")).resolve(),
        refresh_hour=int(os.environ.get("REFRESH_HOUR", "6")),
        timezone=os.environ.get("TZ", "Europe/Amsterdam"),
        market_provider=os.environ.get("MARKET_PROVIDER", "yfinance"),
        scheduler_enabled=os.environ.get("SCHEDULER_ENABLED", "1") == "1",
        screener_batch=int(os.environ.get("SCREENER_BATCH", "200")),
        ask_backend=os.environ.get("ASK_BACKEND", "claude-code"),
        ask_cli_path=os.environ.get("ASK_CLI_PATH", ""),
        ask_cli_model=os.environ.get("ASK_CLI_MODEL", ""),
        ask_model=os.environ.get("ASK_MODEL", "claude-opus-5-5"),
        ask_daily_limit=int(os.environ.get("ASK_DAILY_LIMIT", "50")),
    )
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.upload_dir.mkdir(parents=True, exist_ok=True)
    return cfg
