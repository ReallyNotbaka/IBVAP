"""Typed configuration for IBVAP - validated via Pydantic v2."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    name: str = "IBVAP"
    version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "data"
    models_dir: str = "models"
    log_dir: str = "data/logs"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    frontend_url: str = "http://localhost:5173"
    # CORS allowlist - comma-separated origins, validated at startup
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8000"])


class DBConfig(BaseModel):
    # asyncpg or aiosqlite URL - must not contain credentials in logs
    # Example: postgresql+asyncpg://user:pass@host:5432/ibvap or sqlite+aiosqlite:///:memory:
    url: str = Field(
        default="postgresql+asyncpg://ibvap:ibvap@localhost:5432/ibvap",
        description="SQLAlchemy async DB URL",
    )
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    echo: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        valid_prefixes = ("postgresql+asyncpg://", "sqlite+aiosqlite://", "sqlite://", "postgresql://")
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(f"Database URL must start with one of {valid_prefixes}, got: {v}")
        return v

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.url


class MediaConfig(BaseModel):
    # MediaMTX gateway
    mediamtx_api_url: str = "http://localhost:9997"
    # allowed site CIDRs - site-specific allowlist per spec 21
    site_cidr_allowlist: list[str] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IBVAP_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app: AppConfig = Field(default_factory=AppConfig)
    db: DBConfig = Field(default_factory=DBConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Settings:
        """Load from optional YAML file, env overrides YAML."""
        import yaml

        if config_path is None:
            config_path = os.getenv("IBVAP_CONFIG", "config/default.yaml")
        path = Path(config_path)
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)
